"""Phoenix Autopilot server.

Run with: python3 server.py
The server uses Supabase PostgreSQL. Provider credentials are read only from
the process environment and are never returned by the API.
"""

from __future__ import annotations

import json
import base64
import hashlib
import hmac
import os
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit

import psycopg
from psycopg.rows import dict_row

from content_director import ContentDirector, ContentProviderError
from media_engine import MediaEngine
from search_manager import SearchManager, serialise_results
from tiktok import TikTokClient, TikTokConfigurationError


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL", os.getenv("DATABASE_URL", ""))
ACTIVE_DB_URL: str | None = None
POOLER_REGIONS = (
    "us-east-1",
    "us-west-1",
    "us-west-2",
    "eu-central-1",
    "eu-west-1",
    "ap-southeast-1",
    "ap-northeast-1",
    "sa-east-1",
    "us-east-2",
    "ca-central-1",
    "eu-west-2",
    "eu-west-3",
    "eu-north-1",
    "ap-south-1",
    "ap-southeast-2",
    "ap-northeast-2",
    "us-central-1",
)
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
OAUTH_STATES: dict[str, str] = {}


class AuthError(RuntimeError):
    pass


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HybridRow(dict):
    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class CursorCompat:
    def __init__(self, cursor):
        self.cursor = cursor

    @property
    def rowcount(self):
        return self.cursor.rowcount

    def fetchone(self):
        row = self.cursor.fetchone()
        return HybridRow(row) if row else None

    def fetchall(self):
        return [HybridRow(row) for row in self.cursor.fetchall()]


class ConnectionCompat:
    def __init__(self, url: str):
        self.db = psycopg.connect(url, row_factory=dict_row, connect_timeout=5)

    @staticmethod
    def _translate(query: str) -> str:
        return query.replace("?", "%s")

    def execute(self, query: str, params=None) -> CursorCompat:
        return CursorCompat(self.db.execute(self._translate(query), params or ()))

    def executescript(self, script: str) -> None:
        for statement in script.split(";"):
            if statement.strip():
                self.execute(statement)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if exc_type:
            self.db.rollback()
        else:
            self.db.commit()
        self.db.close()


def connection() -> ConnectionCompat:
    global ACTIVE_DB_URL
    if not SUPABASE_DB_URL:
        raise RuntimeError("SUPABASE_DB_URL is required")
    candidates = [ACTIVE_DB_URL] if ACTIVE_DB_URL else []
    candidates.extend(_supabase_db_candidates())
    last_error = None
    for candidate in dict.fromkeys(item for item in candidates if item):
        try:
            db = ConnectionCompat(candidate)
            ACTIVE_DB_URL = candidate
            return db
        except psycopg.OperationalError as error:
            last_error = error
    raise RuntimeError(f"Unable to connect to Supabase PostgreSQL: {last_error}")


def _supabase_db_candidates() -> list[str]:
    parsed = urlsplit(SUPABASE_DB_URL)
    if not parsed.hostname or not parsed.username or parsed.password is None:
        return [SUPABASE_DB_URL]
    project_ref = os.getenv("SUPABASE_PROJECT_REF", "")
    if not project_ref:
        project_ref = os.getenv("SUPABASE_URL", "").split("//")[-1].split(".")[0]
    if not project_ref:
        return [SUPABASE_DB_URL]
    password = quote(parsed.password, safe="")
    database = parsed.path or "/postgres"
    query = parsed.query or "sslmode=require"
    candidates = [SUPABASE_DB_URL]
    usernames = list(dict.fromkeys((parsed.username, "postgres", f"postgres.{project_ref}")))
    for prefix in ("aws-0", "aws-1"):
        for region in POOLER_REGIONS:
            for username in usernames:
                for port in (6543, 5432):
                    candidates.append(
                        f"postgresql://{quote(username, safe='')}:"
                        f"{password}@{prefix}-{region}.pooler.supabase.com:{port}{database}?{query}"
                    )
    return candidates


def _ensure_column(db: ConnectionCompat, table: str, column: str, definition: str) -> None:
    columns = {
        row["column_name"]
        for row in db.execute(
            "SELECT column_name FROM information_schema.columns WHERE table_schema = 'public' AND table_name = ?",
            (table,),
        ).fetchall()
    }
    if column not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def initialise() -> None:
    if not SUPABASE_DB_URL:
        raise RuntimeError("SUPABASE_DB_URL is required")
    with connection() as db:
        db.executescript((ROOT / "schema.sql").read_text())
        timestamp = now()
        db.execute(
            """INSERT INTO profiles
               (id, display_name, username, timezone, language, niche, created_at, updated_at)
               VALUES ('default', 'Creator', 'creator', 'UTC', 'en', 'AI & technology', ?, ?)
               ON CONFLICT (id) DO NOTHING""",
            (timestamp, timestamp),
        )
        db.execute(
            """INSERT INTO content_settings (id, updated_at) VALUES (1, ?)
               ON CONFLICT (id) DO NOTHING""",
            (timestamp,),
        )


def password_hash(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16_384, r=8, p=1)
    return "scrypt${}${}".format(
        base64.urlsafe_b64encode(salt).decode(), base64.urlsafe_b64encode(digest).decode()
    )


def password_matches(password: str, encoded: str) -> bool:
    try:
        _, salt_text, digest_text = encoded.split("$", 2)
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.scrypt(password.encode("utf-8"), salt=salt, n=16_384, r=8, p=1)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def public_user(row: HybridRow | dict) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "display_name": row["display_name"],
    }


def decode_json(value: str | None, default):
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return default


def json_bytes(payload: object) -> bytes:
    return json.dumps(payload, separators=(",", ":"), default=_json_default).encode("utf-8")


def _json_default(value: object):
    if isinstance(value, (datetime,)):
        return value.isoformat()
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def plan_payload(row: HybridRow) -> dict:
    item = dict(row)
    item["voice_required"] = bool(item.get("voice_required"))
    item["music_required"] = bool(item.get("music_required"))
    item["hashtags"] = decode_json(item.get("hashtags"), [])
    item["visual_instructions"] = decode_json(item.get("visual_instructions"), [])
    item["sources"] = decode_json(item.get("sources"), [])
    return item


def write_notification(
    db: ConnectionCompat, kind: str, title: str, body: str, user_id: str | None = None
) -> None:
    db.execute(
        "INSERT INTO notifications (id, user_id, kind, title, body, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (str(uuid.uuid4()), user_id, kind, title, body, now()),
    )


class Handler(BaseHTTPRequestHandler):
    server_version = "PhoenixAutopilot/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self.pending_headers = {}
        parsed = urlsplit(self.path)
        if parsed.path == "/" or not parsed.path.startswith("/api/"):
            self._serve_static(parsed.path)
            return
        try:
            payload, status = self._get_api(parsed.path, parse_qs(parsed.query))
            self._send_json(payload, status, self.pending_headers)
        except AuthError as error:
            self._send_json({"error": str(error)}, HTTPStatus.UNAUTHORIZED)
        except TikTokConfigurationError as error:
            message = quote(str(error), safe="")
            self.pending_headers["Location"] = f"/app?connected=error&message={message}"
            self._send_json({}, HTTPStatus.SEE_OTHER, self.pending_headers)
        except Exception as error:  # Keep the local server alive and expose a useful error.
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR, self.pending_headers)

    def do_HEAD(self) -> None:
        # TikTok's property verifier may probe with HEAD; serve headers only.
        parsed = urlsplit(self.path)
        if parsed.path == "/" or not parsed.path.startswith("/api/"):
            candidate = self._static_candidate(parsed.path)
            if candidate and candidate.is_file():
                content_type = {
                    ".html": "text/html; charset=utf-8",
                    ".css": "text/css; charset=utf-8",
                    ".js": "text/javascript; charset=utf-8",
                    ".svg": "image/svg+xml",
                    ".txt": "text/plain; charset=utf-8",
                }.get(candidate.suffix, "application/octet-stream")
                body = candidate.read_bytes()
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
            else:
                self._send_static_headers(STATIC / "404.html", HTTPStatus.NOT_FOUND)
        else:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def _static_candidate(self, path: str) -> pathlib.Path | None:
        legal_pages = {
            "/terms": "terms.html",
            "/terms/": "terms.html",
            "/privacy": "privacy.html",
            "/privacy/": "privacy.html",
            "/about": "about.html",
            "/about/": "about.html",
            "/company": "about.html",
            "/company/": "about.html",
            "/help": "help.html",
            "/help/": "help.html",
            "/contact": "contact.html",
            "/contact/": "contact.html",
            "/support": "contact.html",
            "/support/": "contact.html",
            "/security": "security.html",
            "/security/": "security.html",
            "/cookies": "cookies.html",
            "/cookies/": "cookies.html",
            "/cookie-policy": "cookies.html",
            "/cookie-policy/": "cookies.html",
            "/app": "app.html",
            "/app/": "app.html",
            "/login": "auth.html",
            "/login/": "auth.html",
            "/signup": "auth.html",
            "/signup/": "auth.html",
        }
        relative = legal_pages.get(path, "index.html" if path in ("", "/") else path.removeprefix("/"))
        if relative.startswith("static/"):
            relative = relative.removeprefix("static/")
        candidate = (STATIC / relative).resolve()
        if STATIC not in candidate.parents and candidate != STATIC:
            return None
        if not candidate.is_file():
            return None
        return candidate

    def do_POST(self) -> None:
        self.pending_headers = {}
        parsed = urlsplit(self.path)
        if not parsed.path.startswith("/api/"):
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        try:
            payload, status = self._post_api(parsed.path, self._body())
            self._send_json(payload, status, self.pending_headers)
        except AuthError as error:
            self._send_json({"error": str(error)}, HTTPStatus.UNAUTHORIZED, self.pending_headers)
        except ValueError as error:
            self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST, self.pending_headers)
        except TikTokConfigurationError as error:
            self._send_json({"error": str(error)}, HTTPStatus.CONFLICT, self.pending_headers)
        except ContentProviderError as error:
            self._send_json({"error": str(error)}, HTTPStatus.SERVICE_UNAVAILABLE, self.pending_headers)
        except Exception as error:
            self._send_json({"error": str(error)}, HTTPStatus.INTERNAL_SERVER_ERROR, self.pending_headers)

    def _current_user(self) -> HybridRow | None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("phoenix_session")
        if not morsel:
            return None
        token_hash = hashlib.sha256(morsel.value.encode("utf-8")).hexdigest()
        with connection() as db:
            return db.execute(
                """SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id
                   WHERE s.token_hash = ? AND s.expires_at > ? AND u.status = 'ACTIVE'""",
                (token_hash, now()),
            ).fetchone()

    def _require_user(self) -> HybridRow:
        user = self._current_user()
        if not user:
            raise AuthError("Sign in is required")
        return user

    def _set_session(self, user_id: str) -> None:
        raw_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        timestamp = now()
        expires = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat(timespec="seconds")
        with connection() as db:
            db.execute("DELETE FROM sessions WHERE user_id = ? OR expires_at <= ?", (user_id, timestamp))
            db.execute(
                "INSERT INTO sessions (id, user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?, ?)",
                (str(uuid.uuid4()), user_id, token_hash, expires, timestamp),
            )
        secure = " Secure;" if os.getenv("PUBLIC_BASE_URL", "").startswith("https://") else ""
        self.pending_headers["Set-Cookie"] = (
            f"phoenix_session={raw_token}; Path=/; HttpOnly; SameSite=Lax; Max-Age=2592000;{secure}"
        )

    def _clear_session(self) -> None:
        cookie = SimpleCookie(self.headers.get("Cookie", ""))
        morsel = cookie.get("phoenix_session")
        if morsel:
            token_hash = hashlib.sha256(morsel.value.encode("utf-8")).hexdigest()
            with connection() as db:
                db.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
        self.pending_headers["Set-Cookie"] = "phoenix_session=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0"

    def _profile_for_user(self, db: ConnectionCompat, user: HybridRow) -> HybridRow:
        profile = db.execute("SELECT * FROM profiles WHERE id = ?", (user["id"],)).fetchone()
        if profile:
            return profile
        source = db.execute("SELECT * FROM profiles WHERE id = 'default'").fetchone()
        timestamp = now()
        db.execute(
            """INSERT INTO profiles
               (id, display_name, username, timezone, language, niche, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                user["id"],
                user["display_name"],
                user["email"].split("@", 1)[0],
                source["timezone"] if source else "UTC",
                source["language"] if source else "en",
                source["niche"] if source else "AI & technology",
                timestamp,
                timestamp,
            ),
        )
        return db.execute("SELECT * FROM profiles WHERE id = ?", (user["id"],)).fetchone()

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
        if path == "/api/auth/me":
            user = self._current_user()
            return (
                {"authenticated": bool(user), "user": public_user(user) if user else None},
                HTTPStatus.OK,
            )
        if path == "/api/dashboard":
            return self._dashboard(), HTTPStatus.OK
        if path == "/api/content":
            user = self._require_user()
            with connection() as db:
                rows = db.execute(
                    """SELECT c.*, MAX(s.scheduled_at) AS scheduled_at
                       FROM content_plans c LEFT JOIN scheduled_posts s ON s.content_id = c.id
                       WHERE c.user_id = ? GROUP BY c.id ORDER BY c.created_at DESC LIMIT 50""",
                    (user["id"],),
                ).fetchall()
            return {"items": [plan_payload(row) for row in rows]}, HTTPStatus.OK
        if path == "/api/settings":
            user = self._require_user()
            with connection() as db:
                profile = self._profile_for_user(db, user)
                settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
            return {"profile": dict(profile), "settings": dict(settings)}, HTTPStatus.OK
        if path == "/api/notifications":
            user = self._require_user()
            with connection() as db:
                rows = db.execute(
                    "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT 30",
                    (user["id"],),
                ).fetchall()
            return {"items": [dict(row) for row in rows]}, HTTPStatus.OK
        if path == "/api/tiktok/status":
            return self._tiktok_status(), HTTPStatus.OK
        if path == "/api/tiktok/oauth/callback":
            result = self._oauth_callback(query)
            if result.get("connected"):
                self.pending_headers["Location"] = "/app?connected=tiktok"
            else:
                message = quote(str(result.get("error", "TikTok connection was not completed")), safe="")
                self.pending_headers["Location"] = f"/app?connected=error&message={message}"
            return result, HTTPStatus.SEE_OTHER
        return {"error": "Not found"}, HTTPStatus.NOT_FOUND

    def _post_api(self, path: str, body: dict) -> tuple[dict, int]:
        if path == "/api/auth/signup":
            return self._signup(body)
        if path == "/api/auth/login":
            return self._login(body)
        if path == "/api/auth/logout":
            self._clear_session()
            return {"logged_out": True}, HTTPStatus.OK
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

    def _signup(self, body: dict) -> tuple[dict, int]:
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        display_name = str(body.get("display_name", "Creator")).strip() or "Creator"
        if "@" not in email or "." not in email.rsplit("@", 1)[-1]:
            raise ValueError("Enter a valid email address")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        user_id = str(uuid.uuid4())
        timestamp = now()
        with connection() as db:
            if db.execute("SELECT 1 FROM users WHERE email = ?", (email,)).fetchone():
                return {"error": "An account with that email already exists"}, HTTPStatus.CONFLICT
            db.execute(
                """INSERT INTO users
                   (id, email, password_hash, display_name, email_verified, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (user_id, email, password_hash(password), display_name, timestamp, timestamp),
            )
            source = db.execute("SELECT * FROM profiles WHERE id = 'default'").fetchone()
            db.execute(
                """INSERT INTO profiles
                   (id, display_name, username, timezone, language, niche, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    user_id,
                    display_name,
                    email.split("@", 1)[0],
                    source["timezone"] if source else "UTC",
                    source["language"] if source else "en",
                    source["niche"] if source else "AI & technology",
                    timestamp,
                    timestamp,
                ),
            )
        self._set_session(user_id)
        with connection() as db:
            user = db.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return {"authenticated": True, "user": public_user(user)}, HTTPStatus.CREATED

    def _login(self, body: dict) -> tuple[dict, int]:
        email = str(body.get("email", "")).strip().lower()
        password = str(body.get("password", ""))
        with connection() as db:
            user = db.execute("SELECT * FROM users WHERE email = ? AND status = 'ACTIVE'", (email,)).fetchone()
        if not user or not password_matches(password, user["password_hash"]):
            return {"error": "Invalid email or password"}, HTTPStatus.UNAUTHORIZED
        self._set_session(user["id"])
        return {"authenticated": True, "user": public_user(user)}, HTTPStatus.OK

    def _health(self) -> dict:
        try:
            with connection() as db:
                db.execute("SELECT 1").fetchone()
            database = "healthy"
        except psycopg.Error:
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
        user = self._require_user()
        with connection() as db:
            counts = {
                "scheduled": db.execute(
                    """SELECT COUNT(*) FROM scheduled_posts s JOIN content_plans c ON c.id = s.content_id
                       WHERE s.status = 'SCHEDULED' AND c.user_id = ?""",
                    (user["id"],),
                ).fetchone()[0],
                "ready": db.execute(
                    "SELECT COUNT(*) FROM content_plans WHERE user_id = ? AND status = 'READY'",
                    (user["id"],),
                ).fetchone()[0],
                "review": db.execute(
                    "SELECT COUNT(*) FROM content_plans WHERE user_id = ? AND status = 'WAITING_APPROVAL'",
                    (user["id"],),
                ).fetchone()[0],
                "published": db.execute(
                    "SELECT COUNT(*) FROM content_plans WHERE user_id = ? AND status = 'PUBLISHED'",
                    (user["id"],),
                ).fetchone()[0],
                "failed": db.execute(
                    "SELECT COUNT(*) FROM content_plans WHERE user_id = ? AND status = 'FAILED'",
                    (user["id"],),
                ).fetchone()[0],
            }
            settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
            next_post = db.execute(
                """SELECT c.topic, c.format, s.scheduled_at FROM scheduled_posts s
                   JOIN content_plans c ON c.id = s.content_id
                   WHERE s.status = 'SCHEDULED' AND c.user_id = ? ORDER BY s.scheduled_at LIMIT 1""",
                (user["id"],),
            ).fetchone()
            recent = db.execute(
                "SELECT * FROM content_plans WHERE user_id = ? ORDER BY created_at DESC LIMIT 6",
                (user["id"],),
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
        user = self._require_user()
        with connection() as db:
            profile = self._profile_for_user(db, user)
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
                   (id, user_id, topic, niche, format, voice_required, music_required, duration_seconds,
                    hook, script, caption, hashtags, visual_instructions, status, sources, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    plan.id,
                    user["id"],
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
            write_notification(db, "content_ready", "New content plan ready", plan.topic, user["id"])
            row = db.execute("SELECT * FROM content_plans WHERE id = ?", (plan.id,)).fetchone()
        return {"item": plan_payload(row), "used_research": bool(sources)}

    def _update_status(self, content_id: str, body: dict) -> dict:
        user = self._require_user()
        status = str(body.get("status", "")).upper()
        if status not in ALLOWED_STATUSES:
            raise ValueError(f"Unsupported content status: {status}")
        with connection() as db:
            result = db.execute(
                "UPDATE content_plans SET status = ?, updated_at = ? WHERE id = ? AND user_id = ?",
                (status, now(), content_id, user["id"]),
            )
            if result.rowcount == 0:
                return {"error": "Content not found"}
            row = db.execute(
                "SELECT * FROM content_plans WHERE id = ? AND user_id = ?", (content_id, user["id"])
            ).fetchone()
        return {"item": plan_payload(row)}

    def _schedule(self, body: dict) -> dict:
        user = self._require_user()
        content_id = str(body.get("content_id", ""))
        scheduled_at = str(body.get("scheduled_at", "")).strip()
        if not content_id or not scheduled_at:
            raise ValueError("content_id and scheduled_at are required")
        timezone_name = str(body.get("timezone", "UTC"))
        schedule_id = str(uuid.uuid4())
        with connection() as db:
            content = db.execute(
                "SELECT * FROM content_plans WHERE id = ? AND user_id = ?", (content_id, user["id"])
            ).fetchone()
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
            write_notification(db, "scheduled", "Post scheduled", content["topic"], user["id"])
        return {"id": schedule_id, "content_id": content_id, "scheduled_at": scheduled_at}

    def _save_settings(self, body: dict) -> dict:
        user = self._require_user()
        with connection() as db:
            profile_fields = {
                key: str(body[key]).strip()
                for key in ("display_name", "username", "timezone", "language", "niche")
                if key in body
            }
            if profile_fields:
                assignments = ", ".join(f"{key} = ?" for key in profile_fields)
                db.execute(
                    f"UPDATE profiles SET {assignments}, updated_at = ? WHERE id = ?",
                    [*profile_fields.values(), now(), user["id"]],
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
            profile = self._profile_for_user(db, user)
            settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
        return {"profile": dict(profile), "settings": dict(settings)}

    def _toggle_automation(self, body: dict) -> dict:
        user = self._require_user()
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
                user["id"],
            )
        return {"enabled": enabled}

    def _tiktok_status(self) -> dict:
        user = self._require_user()
        client = TikTokClient()
        with connection() as db:
            account = db.execute(
                """SELECT username, status, scopes, expires_at FROM tiktok_accounts
                   WHERE user_id = ? AND status = 'CONNECTED'
                   ORDER BY created_at DESC LIMIT 1""",
                (user["id"],),
            ).fetchone()
        return {
            "configured": client.configured,
            "account": dict(account) if account else None,
            "message": "Ready to connect" if client.configured else "TikTok credentials are still needed",
        }

    def _oauth_start(self) -> dict:
        user = self._require_user()
        client = TikTokClient()
        state = secrets.token_urlsafe(24)
        url = client.authorization_url(state)
        OAUTH_STATES[state] = user["id"]
        return {"url": url}

    def _oauth_callback(self, query: dict) -> dict:
        state = query.get("state", [""])[0]
        code = query.get("code", [""])[0]
        user_id = OAUTH_STATES.get(state)
        if not state or not user_id:
            return {"error": "Invalid or expired OAuth state"}
        OAUTH_STATES.pop(state, None)
        if not code:
            return {"error": query.get("error", ["TikTok authorization was cancelled"])[0]}
        token_data = TikTokClient().exchange_code(code)
        timestamp = now()
        with connection() as db:
            db.execute(
                """INSERT INTO tiktok_accounts
                   (id, user_id, open_id, access_token, refresh_token, scopes, status, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, 'CONNECTED', ?, ?)""",
                (
                    str(uuid.uuid4()),
                    user_id,
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
        user = self._require_user()
        with connection() as db:
            db.execute(
                "UPDATE tiktok_accounts SET status = 'DISCONNECTED', updated_at = ? WHERE user_id = ?",
                (now(), user["id"]),
            )
        return {"connected": False}

    def _read_notification(self, notification_id: str) -> dict:
        user = self._require_user()
        with connection() as db:
            db.execute(
                "UPDATE notifications SET read_at = ? WHERE id = ? AND user_id = ?",
                (now(), notification_id, user["id"]),
            )
        return {"read": True}

    def _serve_static(self, path: str) -> None:
        candidate = self._static_candidate(path)
        status = HTTPStatus.OK
        if candidate is None:
            candidate = STATIC / "404.html"
            status = HTTPStatus.NOT_FOUND
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".txt": "text/plain; charset=utf-8",
        }.get(candidate.suffix, "application/octet-stream")
        body = candidate.read_bytes()
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_static_headers(self, candidate: pathlib.Path, status: int) -> None:
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "text/javascript; charset=utf-8",
            ".svg": "image/svg+xml",
            ".txt": "text/plain; charset=utf-8",
        }.get(candidate.suffix, "application/octet-stream")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(candidate.stat().st_size))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _send_json(self, payload: object, status: int, headers: dict[str, str] | None = None) -> None:
        body = json_bytes(payload)
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        for key, value in (headers or {}).items():
            self.send_header(key, value)
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
