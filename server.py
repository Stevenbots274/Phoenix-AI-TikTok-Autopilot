"""Phoenix Autopilot MVP server.

Run with: python3 server.py
The server uses SQLite and the Python standard library so the first run has no
package installation step. Provider credentials are read only from the process
environment and are never returned by the API.
"""

from __future__ import annotations

import json
import os
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from content_director import ContentDirector
from media_engine import MediaEngine
from search_manager import SearchManager, serialise_results
from tiktok import TikTokClient, TikTokConfigurationError


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
DB_PATH = Path(os.getenv("PHOENIX_DB", ROOT / "phoenix.db"))
ALLOWED_STATUSES = {
    "DRAFT",
    "RESEARCHING",
    "GENERATING",
    "VOICE_GENERATING",
    "VIDEO_RENDERING",
    "READY",
    "WAITING_APPROVAL",
    "SCHEDULED",
    "PUBLISHING",
    "PUBLISHED",
    "FAILED",
    "CANCELLED",
}
OAUTH_STATES: set[str] = set()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connection() -> sqlite3.Connection:
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def initialise() -> None:
    with connection() as db:
        db.executescript((ROOT / "schema.sql").read_text())
        timestamp = now()
        db.execute(
            """INSERT OR IGNORE INTO profiles
               (id, display_name, username, timezone, language, niche, created_at, updated_at)
               VALUES ('default', 'Creator', 'creator', 'UTC', 'en', 'AI & technology', ?, ?)""",
            (timestamp, timestamp),
        )
        db.execute(
            """INSERT OR IGNORE INTO content_settings (id, updated_at) VALUES (1, ?)""",
            (timestamp,),
        )


def decode_json(value: str | None, default):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":")).encode("utf-8")


def plan_payload(row: sqlite3.Row) -> dict:
    item = dict(row)
    item["voice_required"] = bool(item.get("voice_required"))
    item["music_required"] = bool(item.get("music_required"))
    item["hashtags"] = decode_json(item.get("hashtags"), [])
    item["visual_instructions"] = decode_json(item.get("visual_instructions"), [])
    item["sources"] = decode_json(item.get("sources"), [])
    return item


def write_notification(db: sqlite3.Connection, kind: str, title: str, body: str) -> None:
    db.execute(
        "INSERT INTO notifications (id, kind, title, body, created_at) VALUES (?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), kind, title, body, now()),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "PhoenixAutopilot/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlsplit(self.path)
        if parsed.path == "/" or not parsed.path.startswith("/api/"):
            self._serve_static(parsed.path)
            return
        try:
            payload, status = self._get_api(parsed.path, parse_qs(parsed.query))
            self._send_json(payload, status)
        except Exception as error:  # Keep the local server alive and expose a useful error.
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_POST(self) -> None:
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/"):
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload, status = self._post_api(parsed.path, self._body())
            self._send_json(payload, status)
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except TikTokConfigurationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.CONFLICT)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length > 1_000_000:
            raise ValueError("Request body is too large")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            value = json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as error:
            raise ValueError("Request body must be valid JSON") from error
        if not isinstance(value, dict):
            raise ValueError("Request body must be a JSON object")
        return value

    def _get_api(self, path: str, query: dict) -> tuple[dict, int]:
        if path == "/api/health":
            return self._health(), HTTPStatus.OK
        if path == "/api/dashboard":
            return self._dashboard(), HTTPStatus.OK
        if path == "/api/content":
            with connection() as db:
                rows = db.execute(
                    """SELECT c.*, MAX(s.scheduled_at) AS scheduled_at
                       FROM content_plans c LEFT JOIN scheduled_posts s ON s.content_id = c.id
                       GROUP BY c.id ORDER BY c.created_at DESC LIMIT 50"""
                ).fetchall()
            return {"items": [plan_payload(row) for row in rows]}, HTTPStatus.OK
        if path == "/api/settings":
            with connection() as db:
                profile = db.execute("SELECT * FROM profiles WHERE id = 'default'").fetchone()
                settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
            return {"profile": dict(profile), "settings": dict(settings)}, HTTPStatus.OK
        if path == "/api/notifications":
            with connection() as db:
                rows = db.execute(
                    "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 30"
                ).fetchall()
            return {"items": [dict(row) for row in rows]}, HTTPStatus.OK
        if path == "/api/tiktok/status":
            return self._tiktok_status(), HTTPStatus.OK
        if path == "/api/tiktok/oauth/callback":
            return self._oauth_callback(query), HTTPStatus.OK
        return {"error": "Not found"}, HTTPStatus.NOT_FOUND

    def _post_api(self, path: str, body: dict) -> tuple[dict, int]:
        if path == "/api/content/generate":
            return self._generate(body), HTTPStatus.CREATED
        if path == "/api/schedule":
            return self._schedule(body), HTTPStatus.CREATED
        if path == "/api/settings":
            return self._save_settings(body), HTTPStatus.OK
        if path == "/api/automation/toggle":
            return self._toggle_automation(body), HTTPStatus.OK
        if path == "/api/tiktok/oauth/start":
            return self._oauth_start(), HTTPStatus.OK
        if path == "/api/tiktok/disconnect":
            return self._disconnect_tiktok(), HTTPStatus.OK
        if path.startswith("/api/content/") and path.endswith("/status"):
            content_id = path.removeprefix("/api/content/").removesuffix("/status")
            return self._update_status(content_id, body), HTTPStatus.OK
        if path.startswith("/api/notifications/") and path.endswith("/read"):
            notification_id = path.removeprefix("/api/notifications/").removesuffix("/read")
            return self._read_notification(notification_id), HTTPStatus.OK
        return {"error": "Not found"}, HTTPStatus.NOT_FOUND

    def _health(self) -> dict:
        try:
            with connection() as db:
                db.execute("SELECT 1").fetchone()
            database = "healthy"
        except sqlite3.Error:
            database = "down"
        media = MediaEngine().health()
        tiktok = TikTokClient()
        return {
            "database": database,
            "ai_router": "configured" if os.getenv("PHOENIX_AI_API_KEY") else "local_fallback",
            "scheduler": "ready",
            "media": media["status"],
            "tiktok": "configured" if tiktok.configured else "not_configured",
        }

    def _dashboard(self) -> dict:
        with connection() as db:
            counts = {
                "scheduled": db.execute(
                    "SELECT COUNT(*) FROM scheduled_posts WHERE status = 'SCHEDULED'"
                ).fetchone()[0],
                "ready": db.execute(
                    "SELECT COUNT(*) FROM content_plans WHERE status IN ('READY', 'WAITING_APPROVAL')"
                ).fetchone()[0],
                "published": db.execute(
                    "SELECT COUNT(*) FROM content_plans WHERE status = 'PUBLISHED'"
                ).fetchone()[0],
                "failed": db.execute(
                    "SELECT COUNT(*) FROM content_plans WHERE status = 'FAILED'"
                ).fetchone()[0],
            }
            settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
            next_post = db.execute(
                """SELECT c.topic, c.format, s.scheduled_at FROM scheduled_posts s
                   JOIN content_plans c ON c.id = s.content_id
                   WHERE s.status = 'SCHEDULED' ORDER BY s.scheduled_at LIMIT 1"""
            ).fetchone()
            recent = db.execute(
                "SELECT * FROM content_plans ORDER BY created_at DESC LIMIT 6"
            ).fetchall()
        return {
            "counts": counts,
            "automation_enabled": bool(settings["automation_enabled"]),
            "approval_mode": settings["approval_mode"],
            "next_post": dict(next_post) if next_post else None,
            "recent": [plan_payload(row) for row in recent],
            "health": self._health(),
        }

    def _generate(self, body: dict) -> dict:
        with connection() as db:
            profile = db.execute("SELECT * FROM profiles WHERE id = 'default'").fetchone()
            settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
        topic = str(body.get("topic", "")).strip() or None
        niche = str(body.get("niche", profile["niche"])).strip() or profile["niche"]
        requested_format = str(body.get("format", settings["default_format"])).upper()
        instructions = str(body.get("instructions", settings["permanent_instructions"]))
        sources = []
        if body.get("research") and topic:
            sources = SearchManager().search(topic)
        plan = ContentDirector().generate(
            topic=topic,
            niche=niche,
            requested_format=requested_format,
            duration_seconds=int(body.get("duration_seconds", settings["default_duration"])),
            instructions=instructions,
        )
        plan.sources = serialise_results(sources)
        timestamp = now()
        with connection() as db:
            db.execute(
                """INSERT INTO content_plans
                   (id, topic, niche, format, voice_required, music_required, duration_seconds,
                    hook, script, caption, hashtags, visual_instructions, status, sources, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.id,
                    plan.topic,
                    plan.niche,
                    plan.format,
                    int(plan.voice_required),
                    int(plan.music_required),
                    plan.duration_seconds,
                    plan.hook,
                    plan.script,
                    plan.caption,
                    json.dumps(plan.hashtags),
                    json.dumps(plan.visual_instructions),
                    "WAITING_APPROVAL" if settings["approval_mode"] == "approval" else "READY",
                    json.dumps(plan.sources),
                    timestamp,
                    timestamp,
                ),
            )
            db.execute(
                "INSERT INTO scripts (id, content_id, hook, body, cta, created_at) VALUES (?, ?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), plan.id, plan.hook, plan.script, "Follow for more.", timestamp),
            )
            db.execute(
                "INSERT INTO videos (id, content_id, duration, render_status, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), plan.id, plan.duration_seconds, "QUEUED", timestamp),
            )
            write_notification(db, "content_ready", "New content plan ready", plan.topic)
            row = db.execute("SELECT * FROM content_plans WHERE id = ?", (plan.id,)).fetchone()
        return {"item": plan_payload(row), "used_research": bool(sources)}

    def _update_status(self, content_id: str, body: dict) -> dict:
        status = str(body.get("status", "")).upper()
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported content status: {status}")
        with connection() as db:
            result = db.execute(
                "UPDATE content_plans SET status = ?, updated_at = ? WHERE id = ?",
                (status, now(), content_id),
            )
            if result.rowcount == 0:
                return {"error": "Content not found"}
            row = db.execute("SELECT * FROM content_plans WHERE id = ?", (content_id,)).fetchone()
        return {"item": plan_payload(row)}

    def _schedule(self, body: dict) -> dict:
        content_id = str(body.get("content_id", ""))
        scheduled_at = str(body.get("scheduled_at", "")).strip()
        if not content_id or not scheduled_at:
            raise ValueError("content_id and scheduled_at are required")
        timezone_name = str(body.get("timezone", "UTC"))
        schedule_id = str(uuid.uuid4())
        with connection() as db:
            content = db.execute("SELECT * FROM content_plans WHERE id = ?", (content_id,)).fetchone()
            if not content:
                raise ValueError("Content not found")
            db.execute(
                "INSERT INTO scheduled_posts (id, content_id, scheduled_at, timezone, created_at) VALUES (?, ?, ?, ?, ?)",
                (schedule_id, content_id, scheduled_at, timezone_name, now()),
            )
            db.execute(
                "UPDATE content_plans SET status = 'SCHEDULED', updated_at = ? WHERE id = ?",
                (now(), content_id),
            )
            write_notification(db, "scheduled", "Post scheduled", content["topic"])
        return {"id": schedule_id, "content_id": content_id, "scheduled_at": scheduled_at}

    def _save_settings(self, body: dict) -> dict:
        with connection() as db:
            profile_fields = {
                key: str(body[key]).strip()
                for key in ("display_name", "username", "timezone", "language", "niche")
                if key in body
            }
            if profile_fields:
                assignments = ", ".join(f"{key} = ?" for key in profile_fields)
                db.execute(
                    f"UPDATE profiles SET {assignments}, updated_at = ? WHERE id = 'default'",
                    [*profile_fields.values(), now()],
                )
            present = {}
            if "permanent_instructions" in body:
                present["permanent_instructions"] = str(body["permanent_instructions"])
            if "default_format" in body:
                present["default_format"] = str(body["default_format"]).upper()
            if "default_duration" in body:
                present["default_duration"] = max(15, min(int(body["default_duration"]), 90))
            if "approval_mode" in body:
                present["approval_mode"] = str(body["approval_mode"])
            if "posts_per_day" in body:
                present["posts_per_day"] = max(1, min(int(body["posts_per_day"]), 10))
            if "posting_time" in body:
                present["posting_time"] = str(body["posting_time"])
            if present:
                assignments = ", ".join(f"{key} = ?" for key in present)
                db.execute(
                    f"UPDATE content_settings SET {assignments}, updated_at = ? WHERE id = 1",
                    [*present.values(), now()],
                )
            profile = db.execute("SELECT * FROM profiles WHERE id = 'default'").fetchone()
            settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
        return {"profile": dict(profile), "settings": dict(settings)}

    def _toggle_automation(self, body: dict) -> dict:
        enabled = bool(body.get("enabled"))
        with connection() as db:
            db.execute(
                "UPDATE content_settings SET automation_enabled = ?, updated_at = ? WHERE id = 1",
                (int(enabled), now()),
            )
            write_notification(
                db,
                "automation",
                "Autopilot updated",
                "Automation is now active" if enabled else "Automation is paused",
            )
        return {"enabled": enabled}

    def _tiktok_status(self) -> dict:
        client = TikTokClient()
        with connection() as db:
            account = db.execute(
                "SELECT username, status, scopes, expires_at FROM tiktok_accounts ORDER BY created_at DESC LIMIT 1"
            ).fetchone()
        return {
            "configured": client.configured,
            "account": dict(account) if account else None,
            "message": "Ready to connect" if client.configured else "TikTok credentials are still needed",
        }

    def _oauth_start(self) -> dict:
        client = TikTokClient()
        state = secrets.token_urlsafe(24)
        url = client.authorization_url(state)
        OAUTH_STATES.add(state)
        return {"url": url}

    def _oauth_callback(self, query: dict) -> dict:
        state = query.get("state", [""])[0]
        code = query.get("code", [""])[0]
        if not state or state not in OAUTH_STATES:
            return {"error": "Invalid or expired OAuth state"}
        OAUTH_STATES.discard(state)
        if not code:
            return {"error": query.get("error", ["TikTok authorization was cancelled"])[0]}
        token_data = TikTokClient().exchange_code(code)
        timestamp = now()
        with connection() as db:
            db.execute(
                """INSERT INTO tiktok_accounts
                   (id, open_id, access_token, refresh_token, scopes, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 'CONNECTED', ?, ?)""",
                (
                    str(uuid.uuid4()),
                    token_data.get("open_id"),
                    token_data.get("access_token"),
                    token_data.get("refresh_token"),
                    json.dumps(token_data.get("scope", "").split()),
                    timestamp,
                    timestamp,
                ),
            )
        return {"connected": True}

    def _disconnect_tiktok(self) -> dict:
        with connection() as db:
            db.execute("UPDATE tiktok_accounts SET status = 'DISCONNECTED', updated_at = ?", (now(),))
        return {"connected": False}

    def _read_notification(self, notification_id: str) -> dict:
        with connection() as db:
            db.execute("UPDATE notifications SET read_at = ? WHERE id = ?", (now(), notification_id))
        return {"read": True}

    def _serve_static(self, path: str) -> None:
        relative = "index.html" if path in ("", "/") else path.removeprefix("/")
        if relative.startswith("static/"):
            relative = relative.removeprefix("static/")
        candidate = (STATIC / relative).resolve()
        if STATIC not in candidate.parents and candidate != STATIC:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        if not candidate.is_file():
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
        }.get(candidate.suffix, "application/octet-stream")
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_json(self, payload: object, status: int) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    initialise()
    host = os.getenv("PHOENIX_HOST", "127.0.0.1")
    port = int(os.getenv("PHOENIX_PORT", "8000"))
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Phoenix Autopilot running at http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
