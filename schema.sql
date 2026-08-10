CREATE TABLE IF NOT EXISTS users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  display_name TEXT NOT NULL DEFAULT 'Creator',
  status TEXT NOT NULL DEFAULT 'ACTIVE',
  email_verified INTEGER NOT NULL DEFAULT 1,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS profiles (
  id TEXT PRIMARY KEY,
  display_name TEXT NOT NULL DEFAULT 'Creator',
  username TEXT NOT NULL DEFAULT 'creator',
  timezone TEXT NOT NULL DEFAULT 'UTC',
  language TEXT NOT NULL DEFAULT 'en',
  niche TEXT NOT NULL DEFAULT 'AI & technology',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_settings (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  permanent_instructions TEXT NOT NULL DEFAULT '',
  default_format TEXT NOT NULL DEFAULT 'AUTO',
  default_duration INTEGER NOT NULL DEFAULT 35,
  approval_mode TEXT NOT NULL DEFAULT 'approval',
  posts_per_day INTEGER NOT NULL DEFAULT 1,
  posting_time TEXT NOT NULL DEFAULT '20:00',
  posting_days TEXT NOT NULL DEFAULT 'mon,tue,wed,thu,fri,sat,sun',
  automation_enabled INTEGER NOT NULL DEFAULT 0,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS content_plans (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
  topic TEXT NOT NULL,
  niche TEXT NOT NULL,
  format TEXT NOT NULL,
  voice_required INTEGER NOT NULL DEFAULT 0,
  music_required INTEGER NOT NULL DEFAULT 0,
  duration_seconds INTEGER NOT NULL,
  hook TEXT NOT NULL,
  script TEXT NOT NULL,
  caption TEXT NOT NULL,
  hashtags TEXT NOT NULL DEFAULT '[]',
  visual_instructions TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'READY',
  sources TEXT NOT NULL DEFAULT '[]',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scripts (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL REFERENCES content_plans(id) ON DELETE CASCADE,
  hook TEXT NOT NULL,
  body TEXT NOT NULL,
  cta TEXT NOT NULL DEFAULT '',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS videos (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL REFERENCES content_plans(id) ON DELETE CASCADE,
  storage_url TEXT,
  thumbnail_url TEXT,
  duration REAL,
  resolution TEXT NOT NULL DEFAULT '1080x1920',
  file_size BIGINT,
  render_status TEXT NOT NULL DEFAULT 'QUEUED',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS scheduled_posts (
  id TEXT PRIMARY KEY,
  content_id TEXT NOT NULL REFERENCES content_plans(id) ON DELETE CASCADE,
  scheduled_at TIMESTAMPTZ NOT NULL,
  timezone TEXT NOT NULL DEFAULT 'UTC',
  status TEXT NOT NULL DEFAULT 'SCHEDULED',
  retry_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tiktok_accounts (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
  open_id TEXT UNIQUE,
  username TEXT,
  access_token TEXT,
  refresh_token TEXT,
  expires_at TIMESTAMPTZ,
  refresh_expires_at TIMESTAMPTZ,
  scopes TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL DEFAULT 'DISCONNECTED',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS published_posts (
  id TEXT PRIMARY KEY,
  scheduled_post_id TEXT REFERENCES scheduled_posts(id) ON DELETE SET NULL,
  content_id TEXT NOT NULL REFERENCES content_plans(id) ON DELETE CASCADE,
  tiktok_post_id TEXT,
  published_at TIMESTAMPTZ,
  status TEXT NOT NULL DEFAULT 'PENDING',
  response_data TEXT NOT NULL DEFAULT '{}',
  error_message TEXT
);

CREATE TABLE IF NOT EXISTS notifications (
  id TEXT PRIMARY KEY,
  user_id TEXT REFERENCES users(id) ON DELETE CASCADE,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  body TEXT NOT NULL,
  read_at TIMESTAMPTZ,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS api_usage (
  id BIGSERIAL PRIMARY KEY,
  provider TEXT NOT NULL,
  operation TEXT NOT NULL,
  requests INTEGER NOT NULL DEFAULT 1,
  input_units INTEGER NOT NULL DEFAULT 0,
  output_units INTEGER NOT NULL DEFAULT 0,
  execution_ms INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS system_logs (
  id BIGSERIAL PRIMARY KEY,
  level TEXT NOT NULL,
  component TEXT NOT NULL,
  message TEXT NOT NULL,
  metadata TEXT NOT NULL DEFAULT '{}',
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_content_status ON content_plans(status);
CREATE INDEX IF NOT EXISTS idx_content_user ON content_plans(user_id, created_at);
CREATE INDEX IF NOT EXISTS idx_schedule_time ON scheduled_posts(scheduled_at, status);
CREATE INDEX IF NOT EXISTS idx_notifications_read ON notifications(read_at, created_at);
CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(token_hash);
