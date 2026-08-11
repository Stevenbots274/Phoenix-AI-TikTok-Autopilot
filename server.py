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
import threading
import time
import uuid
from datetime import datetime, timedelta, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import psycopg
from psycopg.rows import dict_row

from content_director import ContentDirector, ContentProviderError
from media_engine import MediaEngine
from search_manager import SearchManager, serialise_results
from storage import MediaStorage, StorageError
from tiktok import TikTokClient, TikTokConfigurationError


ROOT = Path(__file__).resolve().parent
STATIC = ROOT / "static"
MEDIA_ROOT = ROOT / "media"
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
AUTOPILOT_HORIZON_DAYS = 7
AUTOPILOT_WORK_PER_CYCLE = 3


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
            """INSERT INTO content_settings (id, approval_mode, updated_at) VALUES (1, 'automatic', ?)
               ON CONFLICT (id) DO NOTHING""",
            (timestamp,),
        )
        _ensure_column(db, "content_plans", "automation_key", "TEXT")
        db.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_content_automation_key "
            "ON content_plans(automation_key) WHERE automation_key IS NOT NULL"
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


def _timezone(name: object) -> timezone | ZoneInfo:
    try:
        return ZoneInfo(str(name or "UTC"))
    except (ZoneInfoNotFoundError, ValueError):
        return timezone.utc


def _automation_key(user_id: str, target_date, slot: int) -> str:
    return f"{user_id}:{target_date.isoformat()}:{slot}"


def _automation_time(target_date, posting_time: object, slot: int, posts_per_day: int, tz) -> str:
    try:
        parsed_time = datetime.strptime(str(posting_time or "20:00"), "%H:%M").time()
    except ValueError:
        parsed_time = datetime.strptime("20:00", "%H:%M").time()
    minutes_after_start = (24 * 60 * slot) // posts_per_day
    local_time = datetime.combine(target_date, parsed_time, tzinfo=tz) + timedelta(minutes=minutes_after_start)
    return local_time.astimezone(timezone.utc).isoformat(timespec="seconds")


def _expiry_from_seconds(value: object) -> str | None:
    try:
        return (datetime.now(timezone.utc) + timedelta(seconds=int(value))).isoformat()
    except (TypeError, ValueError):
        return None


def _token_is_expiring(value: object) -> bool:
    if not value:
        return False
    try:
        expiry = value if isinstance(value, datetime) else datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)
        return expiry <= datetime.now(timezone.utc) + timedelta(seconds=60)
    except ValueError:
        return False


def _access_token(account: HybridRow) -> str:
    token = account["access_token"]
    if not _token_is_expiring(account.get("expires_at")) or not account.get("refresh_token"):
        if not token:
            raise TikTokConfigurationError("The connected TikTok account has no access token.")
        return token
    refreshed = TikTokClient().refresh_access_token(account["refresh_token"])
    token = refreshed.get("access_token")
    if not token:
        raise TikTokConfigurationError("TikTok could not refresh the connected account.")
    with connection() as db:
        db.execute(
            """UPDATE tiktok_accounts SET access_token = ?, refresh_token = ?, expires_at = ?,
               refresh_expires_at = ?, updated_at = ? WHERE id = ?""",
            (
                token,
                refreshed.get("refresh_token", account["refresh_token"]),
                _expiry_from_seconds(refreshed.get("expires_in")),
                _expiry_from_seconds(refreshed.get("refresh_expires_in")),
                now(),
                account.get("id") or account.get("account_id"),
            ),
        )
    return token


def create_content_plan_for_user(
    user_id: str,
    *,
    topic: str | None = None,
    niche: str | None = None,
    requested_format: str | None = None,
    duration_seconds: int | None = None,
    instructions: str | None = None,
    research: bool = False,
    automation_key: str | None = None,
) -> dict:
    with connection() as db:
        user = db.execute("SELECT * FROM users WHERE id = ? AND status = 'ACTIVE'", (user_id,)).fetchone()
        if not user:
            raise ValueError("User not found")
        profile = db.execute("SELECT * FROM profiles WHERE id = ?", (user_id,)).fetchone()
        settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
    if not profile:
        raise ValueError("Creator profile not found")
    selected_topic = str(topic or "").strip() or None
    selected_niche = str(niche or profile["niche"]).strip() or profile["niche"]
    selected_format = str(requested_format or settings["default_format"]).upper()
    selected_instructions = str(
        instructions if instructions is not None else settings["permanent_instructions"]
    )
    sources = SearchManager().search(selected_topic) if research and selected_topic else []
    plan = ContentDirector().generate(
        topic=selected_topic,
        niche=selected_niche,
        requested_format=selected_format,
        duration_seconds=int(duration_seconds or settings["default_duration"]),
        instructions=selected_instructions,
    )
    plan.sources = serialise_results(sources)
    timestamp = now()
    status = "WAITING_APPROVAL" if settings["approval_mode"] == "approval" else "READY"
    with connection() as db:
        result = db.execute(
            """INSERT INTO content_plans
               (id, user_id, automation_key, topic, niche, format, voice_required, music_required, duration_seconds,
                hook, script, caption, hashtags, visual_instructions, status, sources, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT DO NOTHING""",
            (
                plan.id,
                user_id,
                automation_key,
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
                status,
                json.dumps(plan.sources),
                timestamp,
                timestamp,
            ),
        )
        if result.rowcount == 0 and automation_key:
            existing = db.execute(
                "SELECT * FROM content_plans WHERE user_id = ? AND automation_key = ?",
                (user_id, automation_key),
            ).fetchone()
            if existing:
                return {"item": plan_payload(existing), "used_research": bool(sources), "created": False}
        db.execute(
            "INSERT INTO scripts (id, content_id, hook, body, cta, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), plan.id, plan.hook, plan.script, "Follow for more.", timestamp),
        )
        db.execute(
            "INSERT INTO videos (id, content_id, duration, render_status, created_at) VALUES (?, ?, ?, ?, ?)",
            (str(uuid.uuid4()), plan.id, plan.duration_seconds, "QUEUED", timestamp),
        )
        write_notification(db, "content_ready", "New content plan ready", plan.topic, user_id)
        row = db.execute("SELECT * FROM content_plans WHERE id = ?", (plan.id,)).fetchone()
    return {"item": plan_payload(row), "used_research": bool(sources), "created": True}


def render_content_for_user(user_id: str, content_id: str) -> dict:
    MEDIA_ROOT.mkdir(parents=True, exist_ok=True)
    with connection() as db:
        content = db.execute(
            "SELECT * FROM content_plans WHERE id = ? AND user_id = ?", (content_id, user_id)
        ).fetchone()
        video = db.execute(
            "SELECT * FROM videos WHERE content_id = ? ORDER BY created_at DESC LIMIT 1", (content_id,)
        ).fetchone()
    if not content:
        raise ValueError("Content not found")
    if video and video.get("render_status") == "READY" and video.get("storage_url"):
        return dict(video)
    restore_status = content["status"] if content["status"] in ("READY", "SCHEDULED") else "READY"
    video_id = video["id"] if video else str(uuid.uuid4())
    with connection() as db:
        if not video:
            db.execute(
                "INSERT INTO videos (id, content_id, duration, render_status, created_at) VALUES (?, ?, ?, 'QUEUED', ?)",
                (video_id, content_id, content["duration_seconds"], now()),
            )
        db.execute("UPDATE videos SET render_status = ? WHERE id = ?", ("RENDERING", video_id))
        db.execute("UPDATE content_plans SET status = ?, updated_at = ? WHERE id = ?", ("VIDEO_RENDERING", now(), content_id))
    output_path = MEDIA_ROOT / f"{content_id}.mp4"
    try:
        result = MediaEngine().render(
            topic=content["topic"],
            hook=content["hook"],
            script=content["script"],
            duration_seconds=content["duration_seconds"],
            output_path=output_path,
        )
        storage_url = MediaStorage().upload(output_path, f"{user_id}/{content_id}.mp4")
        if not storage_url:
            public_base = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
            if not public_base:
                raise StorageError("PUBLIC_BASE_URL is required when Supabase Storage is unavailable.")
            storage_url = f"{public_base}/media/{quote(output_path.name)}"
        with connection() as db:
            db.execute(
                """UPDATE videos SET storage_url = ?, duration = ?, resolution = ?, file_size = ?,
                   render_status = ? WHERE id = ?""",
                (storage_url, result["duration"], result["resolution"], result["file_size"], "READY", video_id),
            )
            db.execute("UPDATE content_plans SET status = ?, updated_at = ? WHERE id = ?", (restore_status, now(), content_id))
        return {"id": video_id, **result, "storage_url": storage_url, "render_status": "READY"}
    except (StorageError, RuntimeError) as error:
        with connection() as db:
            db.execute("UPDATE videos SET render_status = ? WHERE id = ?", ("FAILED", video_id))
            db.execute("UPDATE content_plans SET status = ?, updated_at = ? WHERE id = ?", (restore_status, now(), content_id))
        raise ContentProviderError(str(error)) from error


def publish_content_for_user(user_id: str, content_id: str, scheduled_post_id: str | None = None) -> dict:
    with connection() as db:
        content = db.execute(
            "SELECT * FROM content_plans WHERE id = ? AND user_id = ?", (content_id, user_id)
        ).fetchone()
        settings = db.execute("SELECT approval_mode FROM content_settings WHERE id = 1").fetchone()
        account = db.execute(
            "SELECT * FROM tiktok_accounts WHERE user_id = ? AND status = 'CONNECTED' ORDER BY created_at DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        existing = db.execute(
            "SELECT 1 FROM published_posts WHERE content_id = ? AND status IN ('INITIATED', 'PROCESSING', 'PUBLISHED') LIMIT 1",
            (content_id,),
        ).fetchone()
    if not content:
        raise ValueError("Content not found")
    if content["status"] == "WAITING_APPROVAL" and settings and settings["approval_mode"] == "automatic":
        with connection() as db:
            db.execute(
                "UPDATE content_plans SET status = 'READY', updated_at = ? WHERE id = ? AND user_id = ?",
                (now(), content_id, user_id),
            )
        content["status"] = "READY"
    if content["status"] not in ("READY", "SCHEDULED", "PUBLISHING"):
        raise ValueError("This post is waiting for approval. Approve it in Review queue or choose automatic publishing in Settings.")
    if existing:
        raise ValueError("This content has already been sent to TikTok")
    if not account:
        raise TikTokConfigurationError("Connect a TikTok account before publishing.")
    video = render_content_for_user(user_id, content_id)
    token = _access_token(account)
    hashtags = " ".join(decode_json(content.get("hashtags"), []))
    caption = f"{content['caption']}\n\n{hashtags}".strip()
    result = TikTokClient().initialize_video_post(token, video["storage_url"], caption)
    data = result.get("data", result) if isinstance(result, dict) else {}
    publish_id = data.get("publish_id")
    if not publish_id:
        raise TikTokConfigurationError("TikTok did not return a publish ID.")
    with connection() as db:
        db.execute(
            """INSERT INTO published_posts
               (id, scheduled_post_id, content_id, tiktok_post_id, status, response_data)
               VALUES (?, ?, ?, ?, 'INITIATED', ?)""",
            (str(uuid.uuid4()), scheduled_post_id, content_id, publish_id, json.dumps(result)),
        )
        db.execute("UPDATE content_plans SET status = 'PUBLISHING', updated_at = ? WHERE id = ?", (now(), content_id))
        if scheduled_post_id:
            db.execute("UPDATE scheduled_posts SET status = 'PUBLISHING' WHERE id = ?", (scheduled_post_id,))
        write_notification(db, "publishing", "TikTok publishing started", content["topic"], user_id)
    return {"status": "PUBLISHING", "publish_id": publish_id}


def _schedule_automation_content(user_id: str, content_id: str, scheduled_at: str, timezone_name: str) -> bool:
    render_content_for_user(user_id, content_id)
    with connection() as db:
        content = db.execute(
            "SELECT * FROM content_plans WHERE id = ? AND user_id = ?", (content_id, user_id)
        ).fetchone()
        if not content or content["status"] != "READY":
            return False
        if db.execute(
            "SELECT 1 FROM scheduled_posts WHERE content_id = ? AND status IN ('SCHEDULED', 'PUBLISHING', 'PUBLISHED') LIMIT 1",
            (content_id,),
        ).fetchone():
            return False
        schedule_id = str(uuid.uuid4())
        db.execute(
            "INSERT INTO scheduled_posts (id, content_id, scheduled_at, timezone, created_at) VALUES (?, ?, ?, ?, ?)",
            (schedule_id, content_id, scheduled_at, timezone_name, now()),
        )
        db.execute(
            "UPDATE content_plans SET status = 'SCHEDULED', updated_at = ? WHERE id = ?",
            (now(), content_id),
        )
        write_notification(db, "scheduled", "Autopilot scheduled a post", content["topic"], user_id)
    return True


def _autopilot_error(user_id: str, error: Exception) -> None:
    message = str(error)[:500] or error.__class__.__name__
    with connection() as db:
        recent = db.execute(
            """SELECT 1 FROM notifications
               WHERE user_id = ? AND kind = 'automation_error' AND body = ?
                 AND created_at > NOW() - INTERVAL '1 hour' LIMIT 1""",
            (user_id, message),
        ).fetchone()
        if not recent:
            write_notification(db, "automation_error", "Autopilot needs attention", message, user_id)


def maintain_autopilot() -> None:
    with connection() as db:
        settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
        users = db.execute(
            "SELECT id FROM users WHERE status = 'ACTIVE' ORDER BY created_at"
        ).fetchall()
    if not settings or not bool(settings["automation_enabled"]):
        return
    work_left = AUTOPILOT_WORK_PER_CYCLE
    for user in users:
        if work_left <= 0:
            break
        try:
            work_left -= _maintain_user_autopilot(user["id"], settings, work_left)
        except Exception as error:
            _autopilot_error(user["id"], error)


def _maintain_user_autopilot(user_id: str, settings: HybridRow, work_limit: int) -> int:
    with connection() as db:
        profile = db.execute("SELECT * FROM profiles WHERE id = ?", (user_id,)).fetchone()
        account = db.execute(
            "SELECT 1 FROM tiktok_accounts WHERE user_id = ? AND status = 'CONNECTED' LIMIT 1",
            (user_id,),
        ).fetchone()
    if not profile:
        return 0
    automatic = settings["approval_mode"] == "automatic"
    if automatic and not account:
        raise TikTokConfigurationError("Connect a TikTok account before enabling automatic publishing.")
    posts_per_day = max(1, min(int(settings["posts_per_day"] or 1), 10))
    tz = _timezone(profile.get("timezone"))
    local_today = datetime.now(tz).date()
    work_done = 0
    for day_offset in range(AUTOPILOT_HORIZON_DAYS):
        target_date = local_today + timedelta(days=day_offset)
        for slot in range(posts_per_day):
            if work_done >= work_limit:
                return work_done
            key = _automation_key(user_id, target_date, slot)
            with connection() as db:
                row = db.execute(
                    "SELECT * FROM content_plans WHERE user_id = ? AND automation_key = ?",
                    (user_id, key),
                ).fetchone()
            scheduled_at = _automation_time(
                target_date,
                settings["posting_time"],
                slot,
                posts_per_day,
                tz,
            )
            if row:
                if automatic and row["status"] == "READY":
                    _schedule_automation_content(user_id, row["id"], scheduled_at, str(profile["timezone"]))
                    work_done += 1
                continue
            result = create_content_plan_for_user(
                user_id,
                instructions=(
                    f"{settings['permanent_instructions']}\nChoose a fresh topic and do not repeat recent content."
                ).strip(),
                duration_seconds=settings["default_duration"],
                automation_key=key,
            )
            work_done += 1
            if automatic and result["item"]["status"] == "READY":
                _schedule_automation_content(user_id, result["item"]["id"], scheduled_at, str(profile["timezone"]))
    return work_done


def process_scheduled_posts() -> None:
    with connection() as db:
        due = db.execute(
            """SELECT s.id AS scheduled_post_id, s.content_id, c.user_id
               FROM scheduled_posts s JOIN content_plans c ON c.id = s.content_id
               WHERE s.status = 'SCHEDULED' AND s.scheduled_at <= ? LIMIT 5""",
            (now(),),
        ).fetchall()
    for item in due:
        with connection() as db:
            claimed = db.execute(
                "UPDATE scheduled_posts SET status = 'PUBLISHING' WHERE id = ? AND status = 'SCHEDULED'",
                (item["scheduled_post_id"],),
            ).rowcount
        if not claimed:
            continue
        try:
            publish_content_for_user(item["user_id"], item["content_id"], item["scheduled_post_id"])
        except Exception as error:
            with connection() as db:
                db.execute("UPDATE scheduled_posts SET status = 'FAILED' WHERE id = ?", (item["scheduled_post_id"],))
                db.execute("UPDATE content_plans SET status = 'FAILED', updated_at = ? WHERE id = ?", (now(), item["content_id"]))
                write_notification(db, "publishing_error", "Scheduled publishing failed", str(error), item["user_id"])


def poll_publishing_posts() -> None:
    with connection() as db:
        rows = db.execute(
            """SELECT p.id AS published_id, p.tiktok_post_id, p.content_id, p.scheduled_post_id, c.user_id,
                      a.access_token, a.refresh_token, a.expires_at, a.id AS account_id
               FROM published_posts p JOIN content_plans c ON c.id = p.content_id
               JOIN tiktok_accounts a ON a.user_id = c.user_id
               WHERE p.status IN ('INITIATED', 'PROCESSING') AND a.status = 'CONNECTED'""",
        ).fetchall()
    for row in rows:
        try:
            token = _access_token(row)
            data = TikTokClient().publish_status(token, row["tiktok_post_id"])
            status = str(data.get("status", "PROCESSING")).upper()
        except Exception:
            continue
        if status not in ("PUBLISH_COMPLETE", "FAILED", "PUBLISH_FAILED"):
            with connection() as db:
                db.execute("UPDATE published_posts SET status = 'PROCESSING' WHERE id = ?", (row["published_id"],))
            continue
        final_status = "PUBLISHED" if status == "PUBLISH_COMPLETE" else "FAILED"
        with connection() as db:
            db.execute(
                "UPDATE published_posts SET status = ?, published_at = ?, error_message = ? WHERE id = ?",
                (final_status, now() if final_status == "PUBLISHED" else None, data.get("fail_reason"), row["published_id"]),
            )
            db.execute("UPDATE content_plans SET status = ?, updated_at = ? WHERE id = ?", (final_status, now(), row["content_id"]))
            if row["scheduled_post_id"]:
                db.execute("UPDATE scheduled_posts SET status = ? WHERE id = ?", (final_status, row["scheduled_post_id"]))
            write_notification(
                db,
                "published" if final_status == "PUBLISHED" else "publishing_error",
                "TikTok post published" if final_status == "PUBLISHED" else "TikTok publishing failed",
                row["content_id"] if final_status == "PUBLISHED" else str(data.get("fail_reason", "TikTok rejected the post")),
                row["user_id"],
            )


def scheduler_loop() -> None:
    while True:
        try:
            maintain_autopilot()
            process_scheduled_posts()
            poll_publishing_posts()
        except Exception:
            pass
        time.sleep(20)


class Handler(BaseHTTPRequestHandler):
    server_version = "PhoenixAutopilot/0.1"

    def log_message(self, format: str, *args) -> None:
        return

    def do_GET(self) -> None:
        self.pending_headers = {}
        parsed = urlsplit(self.path)
        if parsed.path.startswith("/media/"):
            self._serve_media(parsed.path)
            return
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
        if parsed.path.startswith("/media/"):
            candidate = self._media_candidate(parsed.path)
            if candidate:
                self._send_static_headers(candidate, HTTPStatus.OK)
            else:
                self._send_static_headers(STATIC / "404.html", HTTPStatus.NOT_FOUND)
            return
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

    def _media_candidate(self, path: str) -> pathlib.Path | None:
        relative = unquote(path.removeprefix("/media/"))
        candidate = (MEDIA_ROOT / relative).resolve()
        if MEDIA_ROOT not in candidate.parents or not candidate.is_file():
            return None
        return candidate

    def _serve_media(self, path: str) -> None:
        candidate = self._media_candidate(path)
        if not candidate:
            self._send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        body = candidate.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "video/mp4")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=3600")
        self.end_headers()
        self.wfile.write(body)

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
                    """SELECT c.*,
                              (SELECT v.storage_url FROM videos v WHERE v.content_id = c.id ORDER BY v.created_at DESC LIMIT 1) AS video_url,
                              (SELECT v.render_status FROM videos v WHERE v.content_id = c.id ORDER BY v.created_at DESC LIMIT 1) AS render_status,
                              (SELECT MAX(s.scheduled_at) FROM scheduled_posts s WHERE s.content_id = c.id AND s.status = 'SCHEDULED') AS scheduled_at
                       FROM content_plans c
                       WHERE c.user_id = ? ORDER BY c.created_at DESC LIMIT 50""",
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
        if path.startswith("/api/content/") and path.endswith("/publish"):
            content_id = path.removeprefix("/api/content/").removesuffix("/publish")
            user = self._require_user()
            return publish_content_for_user(user["id"], content_id), HTTPStatus.ACCEPTED
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
        return create_content_plan_for_user(
            user["id"],
            topic=topic,
            niche=niche,
            requested_format=requested_format,
            duration_seconds=int(body.get("duration_seconds", settings["default_duration"])),
            instructions=instructions,
            research=bool(body.get("research")),
        )

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
        with connection() as db:
            account = db.execute(
                "SELECT 1 FROM tiktok_accounts WHERE user_id = ? AND status = 'CONNECTED' LIMIT 1",
                (user["id"],),
            ).fetchone()
        if not account:
            raise TikTokConfigurationError("Connect a TikTok account before scheduling a post.")
        render_content_for_user(user["id"], content_id)
        schedule_id = str(uuid.uuid4())
        with connection() as db:
            content = db.execute(
                "SELECT * FROM content_plans WHERE id = ? AND user_id = ?", (content_id, user["id"])
            ).fetchone()
            if not content:
                raise ValueError("Content not found")
            if content["status"] == "WAITING_APPROVAL":
                settings = db.execute("SELECT approval_mode FROM content_settings WHERE id = 1").fetchone()
                if settings and settings["approval_mode"] == "automatic":
                    db.execute(
                        "UPDATE content_plans SET status = 'READY', updated_at = ? WHERE id = ? AND user_id = ?",
                        (now(), content_id, user["id"]),
                    )
                    content["status"] = "READY"
            if content["status"] not in ("READY", "SCHEDULED"):
                raise ValueError("This post is waiting for approval. Approve it in Review queue or choose automatic publishing in Settings.")
            if db.execute(
                "SELECT 1 FROM scheduled_posts WHERE content_id = ? AND status = 'SCHEDULED' LIMIT 1",
                (content_id,),
            ).fetchone():
                raise ValueError("This content is already scheduled")
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
            if present.get("approval_mode") == "automatic":
                db.execute(
                    "UPDATE content_plans SET status = 'READY', updated_at = ? WHERE user_id = ? AND status = 'WAITING_APPROVAL'",
                    (now(), user["id"]),
                )
            profile = self._profile_for_user(db, user)
            settings = db.execute("SELECT * FROM content_settings WHERE id = 1").fetchone()
        return {"profile": dict(profile), "settings": dict(settings)}

    def _toggle_automation(self, body: dict) -> dict:
        user = self._require_user()
        enabled = bool(body.get("enabled"))
        with connection() as db:
            db.execute(
                "UPDATE content_settings SET automation_enabled = ?, approval_mode = CASE WHEN ? = 1 THEN 'automatic' ELSE approval_mode END, updated_at = ? WHERE id = 1",
                (int(enabled), int(enabled), now()),
            )
            if enabled:
                db.execute(
                    "UPDATE content_plans SET status = 'READY', updated_at = ? WHERE user_id = ? AND status = 'WAITING_APPROVAL'",
                    (now(), user["id"]),
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
        open_id = token_data.get("open_id")
        values = (
            user_id,
            open_id,
            token_data.get("access_token"),
            token_data.get("refresh_token"),
            _expiry_from_seconds(token_data.get("expires_in")),
            _expiry_from_seconds(token_data.get("refresh_expires_in")),
            json.dumps(token_data.get("scope", "").split()),
            timestamp,
        )
        with connection() as db:
            existing_by_open_id = db.execute(
                "SELECT id, user_id FROM tiktok_accounts WHERE open_id = ? LIMIT 1", (open_id,)
            ).fetchone() if open_id else None
            if existing_by_open_id and existing_by_open_id["user_id"] != user_id:
                raise TikTokConfigurationError("This TikTok account is already linked to another Phoenix workspace.")
            existing = existing_by_open_id or db.execute(
                "SELECT id, user_id FROM tiktok_accounts WHERE user_id = ? ORDER BY created_at DESC LIMIT 1",
                (user_id,),
            ).fetchone()
            if existing:
                db.execute(
                    """UPDATE tiktok_accounts SET user_id = ?, open_id = ?, access_token = ?, refresh_token = ?,
                       expires_at = ?, refresh_expires_at = ?, scopes = ?, status = 'CONNECTED', updated_at = ?
                       WHERE id = ?""",
                    (*values, existing["id"]),
                )
            else:
                db.execute(
                    """INSERT INTO tiktok_accounts
                       (id, user_id, open_id, access_token, refresh_token, expires_at, refresh_expires_at,
                        scopes, status, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'CONNECTED', ?, ?)""",
                    (str(uuid.uuid4()), *values, timestamp),
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
            ".mp4": "video/mp4",
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
            ".mp4": "video/mp4",
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
    threading.Thread(target=scheduler_loop, name="phoenix-publisher", daemon=True).start()
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
