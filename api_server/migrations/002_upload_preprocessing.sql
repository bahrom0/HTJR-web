ALTER TABLE assets ADD COLUMN original_filename TEXT;
ALTER TABLE assets ADD COLUMN kind TEXT NOT NULL DEFAULT 'original' CHECK(kind IN ('original','prepared'));
ALTER TABLE assets ADD COLUMN width INTEGER CHECK(width IS NULL OR width > 0);
ALTER TABLE assets ADD COLUMN height INTEGER CHECK(height IS NULL OR height > 0);
ALTER TABLE assets ADD COLUMN parent_asset_id TEXT REFERENCES assets(id) ON DELETE RESTRICT;
ALTER TABLE pages ADD COLUMN prepared_asset_id TEXT REFERENCES assets(id) ON DELETE RESTRICT;
ALTER TABLE pages ADD COLUMN preprocessing_recipe_hash TEXT;

CREATE TABLE upload_idempotency (
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  idempotency_key TEXT NOT NULL,
  document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  created_at TEXT NOT NULL,
  PRIMARY KEY(owner_session_id, idempotency_key)
);

CREATE TABLE preprocessing_runs (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  source_asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
  prepared_asset_id TEXT NOT NULL REFERENCES assets(id) ON DELETE RESTRICT,
  pipeline_version TEXT NOT NULL,
  recipe_json TEXT NOT NULL,
  recipe_hash TEXT NOT NULL,
  quality_threshold_version TEXT NOT NULL,
  quality_metrics_json TEXT NOT NULL,
  quality_warnings_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  UNIQUE(owner_session_id, page_id, recipe_hash)
);
