CREATE TABLE users (
  id TEXT PRIMARY KEY,
  email TEXT NOT NULL COLLATE NOCASE UNIQUE,
  name TEXT NOT NULL,
  password_hash TEXT NOT NULL,
  email_verified_at TEXT,
  disabled_at TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE account_ownership_anchors (
  user_id TEXT PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  access_session_id TEXT NOT NULL UNIQUE REFERENCES access_sessions(id) ON DELETE RESTRICT,
  created_at TEXT NOT NULL
);

CREATE TABLE user_sessions (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash BLOB NOT NULL UNIQUE,
  csrf_hash BLOB NOT NULL,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  last_seen_at TEXT NOT NULL,
  revoked_at TEXT,
  user_agent TEXT
);
CREATE INDEX idx_user_sessions_user_active
  ON user_sessions(user_id, revoked_at, expires_at);

CREATE TABLE email_verification_tokens (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash BLOB NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT
);
CREATE INDEX idx_email_verification_user_active
  ON email_verification_tokens(user_id, consumed_at, expires_at);

CREATE TABLE password_reset_tokens (
  id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash BLOB NOT NULL UNIQUE,
  created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL,
  consumed_at TEXT
);
CREATE INDEX idx_password_reset_user_active
  ON password_reset_tokens(user_id, consumed_at, expires_at);

CREATE TABLE account_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  client_key_hash TEXT NOT NULL,
  account_key_hash TEXT NOT NULL,
  attempted_at TEXT NOT NULL,
  succeeded INTEGER NOT NULL DEFAULT 0 CHECK(succeeded IN (0,1))
);
CREATE INDEX idx_account_attempt_window
  ON account_attempts(client_key_hash, account_key_hash, attempted_at, succeeded);

CREATE TABLE auth_security_events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  event_type TEXT NOT NULL,
  user_id TEXT REFERENCES users(id) ON DELETE SET NULL,
  session_id TEXT,
  client_key_hash TEXT,
  occurred_at TEXT NOT NULL
);
CREATE INDEX idx_auth_events_occurred ON auth_security_events(occurred_at);
CREATE INDEX idx_auth_events_user ON auth_security_events(user_id, occurred_at);
