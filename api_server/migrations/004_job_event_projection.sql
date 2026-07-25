ALTER TABLE job_events ADD COLUMN max_attempts INTEGER NOT NULL DEFAULT 3 CHECK(max_attempts > 0);
ALTER TABLE job_events ADD COLUMN cancellation_requested INTEGER NOT NULL DEFAULT 0 CHECK(cancellation_requested IN (0,1));
ALTER TABLE job_events ADD COLUMN error_retryable INTEGER NOT NULL DEFAULT 0 CHECK(error_retryable IN (0,1));

UPDATE job_events
SET max_attempts = COALESCE(
      (SELECT recognition_jobs.max_attempts FROM recognition_jobs WHERE recognition_jobs.id = job_events.job_id),
      max_attempts
    ),
    cancellation_requested = CASE
      WHEN event_type = 'cancellation_requested' THEN 1
      ELSE cancellation_requested
    END,
    error_retryable = CASE
      WHEN state = 'failed_retryable' THEN 1
      ELSE error_retryable
    END;

CREATE INDEX idx_job_events_resume ON job_events(job_id, sequence);
