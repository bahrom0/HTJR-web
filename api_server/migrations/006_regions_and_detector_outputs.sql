ALTER TABLE recognition_regions ADD COLUMN source TEXT NOT NULL DEFAULT 'craft'
  CHECK(source IN ('craft','manual','adjusted'));
ALTER TABLE recognition_regions ADD COLUMN flags_json TEXT NOT NULL DEFAULT '[]';
ALTER TABLE recognition_regions ADD COLUMN detector_version TEXT;
ALTER TABLE recognition_regions ADD COLUMN detector_score REAL;

ALTER TABLE pages ADD COLUMN regions_confirmed_revision INTEGER;
ALTER TABLE pages ADD COLUMN regions_confirmed_at TEXT;

CREATE TABLE craft_detector_outputs (
  id TEXT PRIMARY KEY,
  owner_session_id TEXT NOT NULL REFERENCES access_sessions(id) ON DELETE CASCADE,
  page_id TEXT NOT NULL REFERENCES pages(id) ON DELETE CASCADE,
  job_id TEXT REFERENCES recognition_jobs(id) ON DELETE SET NULL,
  detector_version TEXT NOT NULL,
  thresholds_json TEXT NOT NULL,
  output_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE INDEX idx_regions_page_order ON recognition_regions(page_id, reading_order);
CREATE INDEX idx_craft_outputs_page ON craft_detector_outputs(page_id, created_at);
