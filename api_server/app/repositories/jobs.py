from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.database import Database


TERMINAL_STATES = {"completed", "partial", "failed_terminal", "cancelled"}
ACTIVE_STATES = {"queued", "running"}
JOB_STAGES = {
    "queued", "uploading", "validating", "preprocessing", "detecting_regions",
    "awaiting_region_review", "recognizing_lines", "assembling", "suggesting",
    "ready_for_review", "completed",
}


class JobNotFound(Exception):
    pass


class PageNotReady(Exception):
    pass


class QueueFull(Exception):
    pass


class InvalidJobState(Exception):
    pass


class RetryLimitReached(Exception):
    pass


class LostLease(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Job:
    id: str
    owner_session_id: str
    document_id: str
    page_id: str
    job_kind: str
    state: str
    stage: str
    priority: int
    processed_count: int
    total_count: int
    attempts: int
    max_attempts: int
    claimed_by: str | None
    lease_expires_at: str | None
    heartbeat_at: str | None
    cancellation_requested_at: str | None
    error_code: str | None
    error_retryable: bool
    revision: int
    created_at: str
    updated_at: str
    started_at: str | None
    finished_at: str | None


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _job(row: sqlite3.Row) -> Job:
    data = dict(row)
    data["error_retryable"] = bool(data["error_retryable"])
    return Job(**data)


class JobRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    @staticmethod
    def _select_sql() -> str:
        return """SELECT id,owner_session_id,document_id,page_id,job_kind,state,stage,priority,
                  processed_count,total_count,attempts,max_attempts,claimed_by,
                  lease_expires_at,heartbeat_at,cancellation_requested_at,error_code,
                  error_retryable,revision,created_at,updated_at,started_at,finished_at
                  FROM recognition_jobs"""

    @staticmethod
    def _event(connection: sqlite3.Connection, job_id: str, event_type: str, now: str, error_code: str | None = None) -> None:
        row = connection.execute(
            "SELECT state,stage,processed_count,total_count,attempts,error_code FROM recognition_jobs WHERE id=?",
            (job_id,),
        ).fetchone()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM job_events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO job_events(job_id,sequence,event_type,state,stage,processed_count,total_count,attempt,error_code,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (job_id, sequence, event_type, row["state"], row["stage"], row["processed_count"], row["total_count"], row["attempts"], error_code if error_code is not None else row["error_code"], now),
        )

    def get(self, owner_session_id: str, job_id: str) -> Job:
        with self.database.connect() as connection:
            row = connection.execute(
                self._select_sql() + " WHERE id=? AND owner_session_id=?", (job_id, owner_session_id)
            ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return _job(row)

    def get_internal(self, job_id: str) -> Job:
        with self.database.connect() as connection:
            row = connection.execute(self._select_sql() + " WHERE id=?", (job_id,)).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return _job(row)

    def enqueue(self, owner_session_id: str, page_id: str, idempotency_key: str, *, priority: int, capacity: int, max_attempts: int) -> tuple[Job, bool]:
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            existing = connection.execute(
                self._select_sql() + " WHERE owner_session_id=? AND page_id=? AND idempotency_key=?",
                (owner_session_id, page_id, idempotency_key),
            ).fetchone()
            if existing is not None:
                return _job(existing), True
            page = connection.execute(
                """SELECT p.document_id,p.prepared_asset_id FROM pages p
                   JOIN documents d ON d.id=p.document_id
                   WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
                (page_id, owner_session_id),
            ).fetchone()
            if page is None:
                raise JobNotFound(page_id)
            if page["prepared_asset_id"] is None:
                raise PageNotReady(page_id)
            active = connection.execute(
                "SELECT COUNT(*) FROM recognition_jobs WHERE state IN ('queued','running')"
            ).fetchone()[0]
            if active >= capacity:
                raise QueueFull
            job_id = str(uuid4())
            connection.execute(
                """INSERT INTO recognition_jobs(
                   id,owner_session_id,document_id,page_id,state,stage,priority,attempts,max_attempts,
                   available_at,idempotency_key,created_at,updated_at)
                   VALUES (?,?,?,?, 'queued','queued',?,0,?,?,?,?,?)""",
                (job_id, owner_session_id, page["document_id"], page_id, priority, max_attempts, now, idempotency_key, now, now),
            )
            self._event(connection, job_id, "queued", now)
        return self.get(owner_session_id, job_id), False

    def recover_stale(self, *, at: datetime | None = None) -> int:
        moment = at or _now()
        now = _iso(moment)
        recovered = 0
        with self.database.transaction(immediate=True) as connection:
            connection.execute("DELETE FROM pipeline_locks WHERE lease_expires_at<=?", (now,))
            rows = connection.execute(
                "SELECT id,attempts,max_attempts,cancellation_requested_at FROM recognition_jobs WHERE state='running' AND lease_expires_at<=?",
                (now,),
            ).fetchall()
            for row in rows:
                if row["cancellation_requested_at"] is not None:
                    state, retryable, code, event = "cancelled", 0, None, "cancelled"
                elif row["attempts"] < row["max_attempts"]:
                    state, retryable, code, event = "queued", 1, "worker_lease_expired", "recovered"
                else:
                    state, retryable, code, event = "failed_terminal", 0, "retry_limit_reached", "retry_exhausted"
                finished = now if state in TERMINAL_STATES else None
                connection.execute(
                    """UPDATE recognition_jobs SET state=?,stage=CASE WHEN ?='queued' THEN 'queued' ELSE stage END,
                       claimed_by=NULL,lease_expires_at=NULL,heartbeat_at=NULL,error_code=?,error_retryable=?,
                       finished_at=?,updated_at=?,revision=revision+1 WHERE id=?""",
                    (state, state, code, retryable, finished, now, row["id"]),
                )
                connection.execute(
                    "UPDATE recognition_runs SET finished_at=?,outcome='abandoned' WHERE job_id=? AND attempt=? AND finished_at IS NULL",
                    (now, row["id"], row["attempts"]),
                )
                self._event(connection, row["id"], event, now, code)
                recovered += 1
        return recovered

    def claim(self, worker_id: str, *, lease_seconds: int, at: datetime | None = None) -> Job | None:
        moment = at or _now()
        now, expires = _iso(moment), _iso(moment + timedelta(seconds=lease_seconds))
        self.recover_stale(at=moment)
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                """SELECT id FROM recognition_jobs
                   WHERE state='queued' AND attempts<max_attempts AND available_at<=?
                   ORDER BY priority DESC,created_at ASC,id ASC LIMIT 1""",
                (now,),
            ).fetchone()
            if row is None:
                return None
            job_id = row["id"]
            lock = connection.execute("SELECT 1 FROM pipeline_locks WHERE resource='gpu_pipeline'").fetchone()
            if lock is not None:
                return None
            attempt = connection.execute("SELECT attempts+1 FROM recognition_jobs WHERE id=?", (job_id,)).fetchone()[0]
            connection.execute(
                """UPDATE recognition_jobs SET state='running',stage=CASE WHEN stage='queued' THEN 'validating' ELSE stage END,
                   attempts=?,claimed_by=?,lease_expires_at=?,heartbeat_at=?,started_at=COALESCE(started_at,?),
                   error_code=NULL,error_retryable=0,updated_at=?,revision=revision+1 WHERE id=? AND state='queued'""",
                (attempt, worker_id, expires, now, now, now, job_id),
            )
            connection.execute(
                "INSERT INTO pipeline_locks(resource,worker_id,job_id,heartbeat_at,lease_expires_at) VALUES ('gpu_pipeline',?,?,?,?)",
                (worker_id, job_id, now, expires),
            )
            connection.execute(
                "INSERT INTO recognition_runs(id,job_id,attempt,started_at) VALUES (?,?,?,?)",
                (str(uuid4()), job_id, attempt, now),
            )
            self._event(connection, job_id, "claimed", now)
        return self.get_internal(job_id)

    def heartbeat(self, job_id: str, worker_id: str, *, lease_seconds: int) -> None:
        moment = _now()
        now, expires = _iso(moment), _iso(moment + timedelta(seconds=lease_seconds))
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                """UPDATE recognition_jobs SET heartbeat_at=?,lease_expires_at=?,updated_at=?
                   WHERE id=? AND state='running' AND claimed_by=? AND lease_expires_at>?""",
                (now, expires, now, job_id, worker_id, now),
            )
            if cursor.rowcount != 1:
                raise LostLease(job_id)
            cursor = connection.execute(
                "UPDATE pipeline_locks SET heartbeat_at=?,lease_expires_at=? WHERE resource='gpu_pipeline' AND job_id=? AND worker_id=?",
                (now, expires, job_id, worker_id),
            )
            if cursor.rowcount != 1:
                raise LostLease(job_id)

    def record_worker_heartbeat(self, worker_id: str, *, status: str, current_job_id: str | None, started_at: str) -> None:
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO worker_heartbeats(worker_id,status,current_job_id,heartbeat_at,started_at)
                   VALUES (?,?,?,?,?) ON CONFLICT(worker_id) DO UPDATE SET
                   status=excluded.status,current_job_id=excluded.current_job_id,heartbeat_at=excluded.heartbeat_at""",
                (worker_id, status, current_job_id, now, started_at),
            )

    def worker_is_fresh(self, *, stale_seconds: int) -> bool:
        cutoff = _iso(_now() - timedelta(seconds=stale_seconds))
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM worker_heartbeats WHERE heartbeat_at>=? AND status IN ('idle','running') LIMIT 1", (cutoff,)
            ).fetchone() is not None

    def cancellation_requested(self, job_id: str, worker_id: str) -> bool:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT cancellation_requested_at FROM recognition_jobs WHERE id=? AND state='running' AND claimed_by=?",
                (job_id, worker_id),
            ).fetchone()
        if row is None:
            raise LostLease(job_id)
        return row[0] is not None

    def request_cancel(self, owner_session_id: str, job_id: str) -> Job:
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT state FROM recognition_jobs WHERE id=? AND owner_session_id=?", (job_id, owner_session_id)).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            if row["state"] == "queued":
                connection.execute("UPDATE recognition_jobs SET state='cancelled',finished_at=?,updated_at=?,revision=revision+1 WHERE id=?", (now, now, job_id))
                self._event(connection, job_id, "cancelled", now)
            elif row["state"] == "running":
                connection.execute("UPDATE recognition_jobs SET cancellation_requested_at=COALESCE(cancellation_requested_at,?),updated_at=?,revision=revision+1 WHERE id=?", (now, now, job_id))
                self._event(connection, job_id, "cancellation_requested", now)
            elif row["state"] not in TERMINAL_STATES:
                raise InvalidJobState(row["state"])
        return self.get(owner_session_id, job_id)

    def save_stage(self, job_id: str, worker_id: str, stage: str, *, processed_count: int, total_count: int, outcome: str = "completed") -> None:
        if stage not in JOB_STAGES or processed_count < 0 or total_count < 0 or processed_count > total_count or outcome not in {"completed", "partial"}:
            raise ValueError("Invalid persisted stage counters")
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT attempts,state,claimed_by FROM recognition_jobs WHERE id=?", (job_id,)).fetchone()
            if row is None or row["state"] != "running" or row["claimed_by"] != worker_id:
                raise LostLease(job_id)
            prior_completed = connection.execute(
                "SELECT outcome,processed_count,total_count FROM job_stage_results WHERE job_id=? AND stage=? AND outcome='completed' ORDER BY attempt LIMIT 1",
                (job_id, stage),
            ).fetchone()
            if prior_completed is not None:
                if tuple(prior_completed) != (outcome, processed_count, total_count):
                    raise InvalidJobState("completed stage checkpoint conflict")
                return
            existing = connection.execute("SELECT outcome,processed_count,total_count FROM job_stage_results WHERE job_id=? AND attempt=? AND stage=?", (job_id, row["attempts"], stage)).fetchone()
            if existing is not None:
                if tuple(existing) != (outcome, processed_count, total_count):
                    raise InvalidJobState("stage checkpoint conflict")
                return
            connection.execute(
                "INSERT INTO job_stage_results(id,job_id,attempt,stage,outcome,processed_count,total_count,created_at) VALUES (?,?,?,?,?,?,?,?)",
                (str(uuid4()), job_id, row["attempts"], stage, outcome, processed_count, total_count, now),
            )
            connection.execute(
                "UPDATE recognition_jobs SET stage=?,processed_count=?,total_count=?,updated_at=?,revision=revision+1 WHERE id=?",
                (stage, processed_count, total_count, now, job_id),
            )
            self._event(connection, job_id, "stage_completed" if outcome == "completed" else "stage_partial", now)

    def completed_stages(self, job_id: str) -> frozenset[str]:
        with self.database.connect() as connection:
            rows = connection.execute("SELECT DISTINCT stage FROM job_stage_results WHERE job_id=? AND outcome='completed'", (job_id,)).fetchall()
        return frozenset(row[0] for row in rows)

    def finish(self, job_id: str, worker_id: str, state: str, *, error_code: str | None = None) -> Job:
        if state not in {"completed", "partial", "failed_retryable", "failed_terminal", "cancelled"}:
            raise ValueError("Invalid final job state")
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT * FROM recognition_jobs WHERE id=? AND state='running' AND claimed_by=?", (job_id, worker_id)).fetchone()
            if row is None:
                raise LostLease(job_id)
            if row["cancellation_requested_at"] is not None:
                state, error_code = "cancelled", None
            elif state == "failed_retryable" and row["attempts"] >= row["max_attempts"]:
                state, error_code = "failed_terminal", "retry_limit_reached"
            retryable = int(state == "failed_retryable")
            connection.execute(
                """UPDATE recognition_jobs SET state=?,error_code=?,error_retryable=?,claimed_by=NULL,
                   lease_expires_at=NULL,heartbeat_at=NULL,finished_at=?,updated_at=?,revision=revision+1 WHERE id=?""",
                (state, error_code, retryable, now, now, job_id),
            )
            connection.execute("UPDATE recognition_runs SET finished_at=?,outcome=? WHERE job_id=? AND attempt=?", (now, state, job_id, row["attempts"]))
            connection.execute("DELETE FROM pipeline_locks WHERE resource='gpu_pipeline' AND job_id=? AND worker_id=?", (job_id, worker_id))
            self._event(connection, job_id, state, now, error_code)
        return self.get_internal(job_id)

    def retry(self, owner_session_id: str, job_id: str) -> Job:
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT state,attempts,max_attempts FROM recognition_jobs WHERE id=? AND owner_session_id=?", (job_id, owner_session_id)).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            if row["attempts"] >= row["max_attempts"]:
                raise RetryLimitReached(job_id)
            if row["state"] == "queued":
                return self.get(owner_session_id, job_id)
            if row["state"] != "failed_retryable":
                raise InvalidJobState(row["state"])
            connection.execute(
                """UPDATE recognition_jobs SET state='queued',stage='queued',available_at=?,claimed_by=NULL,
                   lease_expires_at=NULL,heartbeat_at=NULL,cancellation_requested_at=NULL,error_code=NULL,
                   error_retryable=0,finished_at=NULL,updated_at=?,revision=revision+1 WHERE id=?""",
                (now, now, job_id),
            )
            self._event(connection, job_id, "retried", now)
        return self.get(owner_session_id, job_id)
