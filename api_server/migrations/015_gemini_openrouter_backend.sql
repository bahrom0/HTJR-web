-- migrate: foreign_keys_off

CREATE TABLE recognition_regions_new (
  id TEXT PRIMARY KEY,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  polygon_json TEXT NOT NULL,
  reading_order INTEGER NOT NULL,
  revision INTEGER NOT NULL DEFAULT 1,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  source TEXT NOT NULL DEFAULT 'craft'
    CHECK(source IN ('craft','kraken','gemini_openrouter','manual','adjusted')),
  flags_json TEXT NOT NULL DEFAULT '[]',
  detector_version TEXT,
  detector_score REAL,
  UNIQUE(page_id, reading_order)
);

INSERT INTO recognition_regions_new
SELECT * FROM recognition_regions;
DROP TABLE recognition_regions;
ALTER TABLE recognition_regions_new RENAME TO recognition_regions;
CREATE INDEX idx_regions_page_order ON recognition_regions(page_id, reading_order);

CREATE TABLE recognition_run_regions_new (
  id TEXT PRIMARY KEY,
  recognition_run_id TEXT NOT NULL REFERENCES recognition_runs(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  source_region_id TEXT NOT NULL,
  polygon_json TEXT NOT NULL,
  reading_order INTEGER NOT NULL CHECK(reading_order >= 0),
  source TEXT NOT NULL CHECK(source IN ('craft','kraken','gemini_openrouter','manual','adjusted')),
  flags_json TEXT NOT NULL,
  detector_version TEXT,
  detector_score REAL,
  page_revision INTEGER NOT NULL CHECK(page_revision > 0),
  created_at TEXT NOT NULL,
  UNIQUE(recognition_run_id, source_region_id),
  UNIQUE(recognition_run_id, reading_order)
);

INSERT INTO recognition_run_regions_new
SELECT * FROM recognition_run_regions;
DROP TABLE recognition_run_regions;
ALTER TABLE recognition_run_regions_new RENAME TO recognition_run_regions;
CREATE INDEX idx_run_regions_order ON recognition_run_regions(recognition_run_id, reading_order);

CREATE TABLE worker_model_readiness_new (
  worker_id TEXT NOT NULL,
  model_name TEXT NOT NULL CHECK(model_name IN ('craft','kraken','trocr','gemini_openrouter')),
  status TEXT NOT NULL CHECK(status IN ('ready','unavailable')),
  model_version TEXT,
  evidence_json TEXT,
  error_code TEXT,
  warmed_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(worker_id, model_name)
);

INSERT INTO worker_model_readiness_new
SELECT * FROM worker_model_readiness;
DROP TABLE worker_model_readiness;
ALTER TABLE worker_model_readiness_new RENAME TO worker_model_readiness;

CREATE TABLE detector_outputs_new (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  job_id TEXT REFERENCES recognition_jobs(id) ON DELETE SET NULL,
  recognition_run_id TEXT REFERENCES recognition_runs(id) ON DELETE SET NULL,
  detector_name TEXT NOT NULL CHECK(detector_name IN ('craft','kraken','gemini_openrouter')),
  detector_version TEXT NOT NULL,
  config_json TEXT NOT NULL,
  output_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO detector_outputs_new
SELECT * FROM detector_outputs;
DROP TABLE detector_outputs;
ALTER TABLE detector_outputs_new RENAME TO detector_outputs;
CREATE INDEX idx_detector_outputs_page ON detector_outputs(page_id, created_at);

CREATE TABLE line_reconstruction_audits_new (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  job_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
  recognition_run_id TEXT NOT NULL REFERENCES recognition_runs(id) ON DELETE CASCADE,
  detector_name TEXT NOT NULL CHECK(detector_name IN ('craft','kraken','gemini_openrouter')),
  schema_version INTEGER NOT NULL CHECK(schema_version > 0),
  parameters_json TEXT NOT NULL,
  source_regions_json TEXT NOT NULL,
  line_regions_json TEXT NOT NULL,
  merges_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

INSERT INTO line_reconstruction_audits_new
SELECT * FROM line_reconstruction_audits;
DROP TABLE line_reconstruction_audits;
ALTER TABLE line_reconstruction_audits_new RENAME TO line_reconstruction_audits;
CREATE INDEX idx_line_reconstruction_audits_run
  ON line_reconstruction_audits(recognition_run_id, created_at);
