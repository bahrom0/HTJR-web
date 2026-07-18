CREATE TABLE access_codes (
  id TEXT PRIMARY KEY, salt BLOB NOT NULL, code_hash BLOB NOT NULL, created_at TEXT NOT NULL,
  expires_at TEXT NOT NULL, consumed_at TEXT, label TEXT
);
CREATE TABLE access_sessions (
  id TEXT PRIMARY KEY, token_hash BLOB NOT NULL UNIQUE, csrf_hash BLOB NOT NULL,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL, revoked_at TEXT, last_seen_at TEXT NOT NULL
);
CREATE TABLE access_attempts (
  id INTEGER PRIMARY KEY AUTOINCREMENT, client_key TEXT NOT NULL, attempted_at TEXT NOT NULL, succeeded INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_access_attempts_client_time ON access_attempts(client_key, attempted_at);
CREATE TABLE documents (
  id TEXT PRIMARY KEY, owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  title TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'draft', revision INTEGER NOT NULL DEFAULT 1 CHECK(revision > 0),
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, deleted_at TEXT
);
CREATE INDEX idx_documents_owner ON documents(owner_session_id);
CREATE TABLE assets (
  id TEXT PRIMARY KEY, owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  document_id TEXT REFERENCES documents(id) ON DELETE CASCADE, storage_key TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL, byte_size INTEGER NOT NULL CHECK(byte_size >= 0), media_type TEXT NOT NULL,
  state TEXT NOT NULL CHECK(state IN ('temporary','committed','deleted')), created_at TEXT NOT NULL,
  committed_at TEXT, expires_at TEXT, deleted_at TEXT
);
CREATE TABLE pages (
  id TEXT PRIMARY KEY, document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  source_asset_id TEXT REFERENCES assets(id) ON DELETE RESTRICT, page_index INTEGER NOT NULL CHECK(page_index >= 0),
  revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(document_id, page_index)
);
CREATE TABLE recognition_regions (
  id TEXT PRIMARY KEY, page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  polygon_json TEXT NOT NULL, reading_order INTEGER NOT NULL, revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, UNIQUE(page_id, reading_order)
);
CREATE TABLE text_lines (
  id TEXT PRIMARY KEY, region_id TEXT NOT NULL REFERENCES recognition_regions(id) ON DELETE CASCADE,
  line_index INTEGER NOT NULL, bbox_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  UNIQUE(region_id, line_index)
);
CREATE TABLE recognition_jobs (
  id TEXT PRIMARY KEY, owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  state TEXT NOT NULL, revision INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  started_at TEXT, finished_at TEXT, error_code TEXT
);
CREATE TABLE recognition_runs (
  id TEXT PRIMARY KEY, job_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
  attempt INTEGER NOT NULL CHECK(attempt > 0), model_manifest_sha256 TEXT, started_at TEXT NOT NULL, finished_at TEXT,
  outcome TEXT, UNIQUE(job_id, attempt)
);
CREATE TABLE text_versions (
  id TEXT PRIMARY KEY, line_id TEXT NOT NULL REFERENCES text_lines(id) ON DELETE CASCADE,
  kind TEXT NOT NULL CHECK(kind IN ('raw','suggested','confirmed')), text TEXT NOT NULL,
  revision INTEGER NOT NULL, created_at TEXT NOT NULL, created_by_session_id TEXT REFERENCES access_sessions(id) ON DELETE SET NULL,
  UNIQUE(line_id, kind, revision)
);
CREATE TABLE corrections (
  id TEXT PRIMARY KEY, line_id TEXT NOT NULL REFERENCES text_lines(id) ON DELETE CASCADE,
  from_version_id TEXT NOT NULL REFERENCES text_versions(id) ON DELETE RESTRICT,
  to_version_id TEXT NOT NULL REFERENCES text_versions(id) ON DELETE RESTRICT,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE, created_at TEXT NOT NULL
);
CREATE TABLE uncertain_items (
  id TEXT PRIMARY KEY, line_id TEXT NOT NULL REFERENCES text_lines(id) ON DELETE CASCADE,
  reason_code TEXT NOT NULL, evidence_json TEXT NOT NULL, resolved_at TEXT, created_at TEXT NOT NULL
);
CREATE TABLE export_artifacts (
  id TEXT PRIMARY KEY, owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE RESTRICT, format TEXT NOT NULL, created_at TEXT NOT NULL
);
