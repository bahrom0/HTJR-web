ALTER TABLE recognition_jobs ADD COLUMN page_id TEXT REFERENCES pages(id) ON DELETE CASCADE;
ALTER TABLE recognition_jobs ADD COLUMN job_kind TEXT NOT NULL DEFAULT 'page_recognition';
ALTER TABLE recognition_jobs ADD COLUMN stage TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE recognition_jobs ADD COLUMN priority INTEGER NOT NULL DEFAULT 0;
ALTER TABLE recognition_jobs ADD COLUMN processed_count INTEGER NOT NULL DEFAULT 0 CHECK(processed_count >= 0);
ALTER TABLE recognition_jobs ADD COLUMN total_count INTEGER NOT NULL DEFAULT 0 CHECK(total_count >= 0);
ALTER TABLE recognition_jobs ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0);
ALTER TABLE recognition_jobs ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts > 0);
ALTER TABLE recognition_jobs ADD COLUMN available_at TEXT;
ALTER TABLE recognition_jobs ADD COLUMN claimed_by TEXT;
ALTER TABLE recognition_jobs ADD COLUMN lease_expires_at TEXT;
ALTER TABLE recognition_jobs ADD COLUMN heartbeat_at TEXT;
ALTER TABLE recognition_jobs ADD COLUMN cancellation_requested_at TEXT;
ALTER TABLE recognition_jobs ADD COLUMN idempotency_key TEXT;
ALTER TABLE recognition_jobs ADD COLUMN error_retryable INTEGER NOT NULL DEFAULT 0 CHECK(error_retryable IN (0,1));

UPDATE recognition_jobs SET available_at=created_at WHERE available_at IS NULL;

CREATE UNIQUE INDEX idx_recognition_jobs_idempotency
  ON recognition_jobs(owner_session_id,page_id,idempotency_key)
  WHERE idempotency_key IS NOT NULL;
CREATE INDEX idx_recognition_jobs_queue
  ON recognition_jobs(state,priority DESC,available_at,created_at);
CREATE INDEX idx_recognition_jobs_lease
  ON recognition_jobs(state,lease_expires_at);

CREATE TABLE job_events (
  job_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
  sequence INTEGER NOT NULL CHECK(sequence > 0),
  event_type TEXT NOT NULL,
  state TEXT NOT NULL,
  stage TEXT NOT NULL,
  processed_count INTEGER NOT NULL CHECK(processed_count >= 0),
  total_count INTEGER NOT NULL CHECK(total_count >= 0),
  attempt INTEGER NOT NULL CHECK(attempt >= 0),
  error_code TEXT,
  created_at TEXT NOT NULL,
  PRIMARY KEY(job_id,sequence)
);

CREATE TABLE job_stage_results (
  id TEXT PRIMARY KEY,
  job_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
  attempt INTEGER NOT NULL CHECK(attempt > 0),
  stage TEXT NOT NULL,
  outcome TEXT NOT NULL CHECK(outcome IN ('completed','partial')),
  processed_count INTEGER NOT NULL CHECK(processed_count >= 0),
  total_count INTEGER NOT NULL CHECK(total_count >= 0),
  created_at TEXT NOT NULL,
  UNIQUE(job_id,attempt,stage)
);

CREATE TABLE worker_heartbeats (
  worker_id TEXT PRIMARY KEY,
  status TEXT NOT NULL CHECK(status IN ('idle','running','stopping')),
  current_job_id TEXT REFERENCES recognition_jobs(id) ON DELETE SET NULL,
  heartbeat_at TEXT NOT NULL,
  started_at TEXT NOT NULL
);

CREATE TABLE pipeline_locks (
  resource TEXT PRIMARY KEY CHECK(resource='gpu_pipeline'),
  worker_id TEXT NOT NULL,
  job_id TEXT NOT NULL REFERENCES recognition_jobs(id) ON DELETE CASCADE,
  heartbeat_at TEXT NOT NULL,
  lease_expires_at TEXT NOT NULL
);
