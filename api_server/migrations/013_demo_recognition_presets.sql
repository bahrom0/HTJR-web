CREATE TABLE demo_recognition_presets (
  image_sha256 TEXT PRIMARY KEY CHECK(length(image_sha256) = 64),
  raw_text TEXT NOT NULL CHECK(length(raw_text) <= 10000),
  original_filename TEXT,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
