CREATE TABLE editor_line_drafts (
  line_id TEXT PRIMARY KEY REFERENCES text_lines(id) ON DELETE CASCADE,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  text TEXT NOT NULL,
  revision INTEGER NOT NULL CHECK(revision > 0),
  updated_at TEXT NOT NULL
);

CREATE INDEX idx_editor_line_drafts_owner ON editor_line_drafts(owner_session_id);

CREATE TABLE editor_confirmation_idempotency (
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  idempotency_key TEXT NOT NULL,
  line_id TEXT NOT NULL REFERENCES text_lines(id) ON DELETE CASCADE,
  revision INTEGER NOT NULL,
  created_at TEXT NOT NULL,
  PRIMARY KEY(owner_session_id, idempotency_key)
);
