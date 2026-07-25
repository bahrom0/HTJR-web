ALTER TABLE recognition_runs ADD COLUMN prepared_asset_id TEXT REFERENCES assets(id) ON DELETE RESTRICT;
ALTER TABLE recognition_runs ADD COLUMN prepared_asset_sha256 TEXT;
ALTER TABLE recognition_runs ADD COLUMN page_revision INTEGER;
ALTER TABLE recognition_runs ADD COLUMN pipeline_manifest_sha256 TEXT;
ALTER TABLE recognition_runs ADD COLUMN craft_detector_version TEXT;
ALTER TABLE recognition_runs ADD COLUMN craft_thresholds_json TEXT;
ALTER TABLE recognition_runs ADD COLUMN trocr_model_version TEXT;
ALTER TABLE recognition_runs ADD COLUMN rslora_adapter_version TEXT;
ALTER TABLE recognition_runs ADD COLUMN device TEXT;
ALTER TABLE recognition_runs ADD COLUMN dtype TEXT;
ALTER TABLE recognition_runs ADD COLUMN generation_parameters_json TEXT;

ALTER TABLE craft_detector_outputs ADD COLUMN recognition_run_id TEXT REFERENCES recognition_runs(id) ON DELETE SET NULL;

CREATE TABLE worker_model_readiness (
  worker_id TEXT NOT NULL,
  model_name TEXT NOT NULL CHECK(model_name IN ('craft','trocr')),
  status TEXT NOT NULL CHECK(status IN ('ready','unavailable')),
  model_version TEXT,
  evidence_json TEXT,
  error_code TEXT,
  warmed_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(worker_id, model_name)
);

CREATE TABLE recognition_run_regions (
  id TEXT PRIMARY KEY,
  recognition_run_id TEXT NOT NULL REFERENCES recognition_runs(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  source_region_id TEXT NOT NULL,
  polygon_json TEXT NOT NULL,
  reading_order INTEGER NOT NULL CHECK(reading_order >= 0),
  source TEXT NOT NULL CHECK(source IN ('craft','manual','adjusted')),
  flags_json TEXT NOT NULL,
  detector_version TEXT,
  detector_score REAL,
  page_revision INTEGER NOT NULL CHECK(page_revision > 0),
  created_at TEXT NOT NULL,
  UNIQUE(recognition_run_id, source_region_id),
  UNIQUE(recognition_run_id, reading_order)
);

CREATE TABLE recognition_line_crops (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  recognition_run_id TEXT NOT NULL REFERENCES recognition_runs(id) ON DELETE CASCADE,
  run_region_id TEXT NOT NULL UNIQUE REFERENCES recognition_run_regions(id) ON DELETE CASCADE,
  storage_key TEXT NOT NULL UNIQUE,
  sha256 TEXT NOT NULL,
  byte_size INTEGER NOT NULL CHECK(byte_size > 0),
  width INTEGER NOT NULL CHECK(width > 0),
  height INTEGER NOT NULL CHECK(height > 0),
  padding_fraction REAL NOT NULL CHECK(padding_fraction >= 0 AND padding_fraction <= 0.25),
  created_at TEXT NOT NULL
);

CREATE TABLE recognition_line_results (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  recognition_run_id TEXT NOT NULL REFERENCES recognition_runs(id) ON DELETE CASCADE,
  run_region_id TEXT NOT NULL REFERENCES recognition_run_regions(id) ON DELETE CASCADE,
  crop_id TEXT NOT NULL REFERENCES recognition_line_crops(id) ON DELETE RESTRICT,
  line_attempt INTEGER NOT NULL CHECK(line_attempt > 0),
  state TEXT NOT NULL CHECK(state IN ('completed','failed_retryable','failed_terminal')),
  raw_text TEXT,
  generation_json TEXT,
  duration_ms INTEGER,
  error_code TEXT,
  error_retryable INTEGER NOT NULL DEFAULT 0 CHECK(error_retryable IN (0,1)),
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(recognition_run_id, run_region_id, line_attempt)
);

CREATE INDEX idx_run_regions_order ON recognition_run_regions(recognition_run_id, reading_order);
CREATE INDEX idx_line_results_latest ON recognition_line_results(recognition_run_id, run_region_id, line_attempt DESC);

CREATE TABLE page_raw_results (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  recognition_run_id TEXT NOT NULL UNIQUE REFERENCES recognition_runs(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  raw_text TEXT NOT NULL,
  is_partial INTEGER NOT NULL CHECK(is_partial IN (0,1)),
  created_at TEXT NOT NULL
);
