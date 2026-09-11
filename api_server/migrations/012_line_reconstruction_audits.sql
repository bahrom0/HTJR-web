CREATE TABLE line_reconstruction_audits (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  job_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
  recognition_run_id TEXT NOT NULL REFERENCES recognition_runs(id) ON DELETE CASCADE,
  detector_name TEXT NOT NULL CHECK(detector_name IN ('craft','kraken')),
  schema_version INTEGER NOT NULL CHECK(schema_version > 0),
  parameters_json TEXT NOT NULL,
  source_regions_json TEXT NOT NULL,
  line_regions_json TEXT NOT NULL,
  merges_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_line_reconstruction_audits_run
  ON line_reconstruction_audits(recognition_run_id, created_at);
