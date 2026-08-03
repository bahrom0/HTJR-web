from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.database import Database


TERMINAL_STATES = {"completed", "partial", "failed_terminal", "cancelled"}
ACTIVE_STATES = {"queued", "running", "awaiting_region_review"}
JOB_STAGES = {
    "queued", "uploading", "validating", "preprocessing", "detecting_regions",
    "awaiting_region_review", "recognizing_lines", "assembling", "suggesting",
    "ready_for_review", "completed",
}


class JobNotFound(Exception):
    pass


class PageNotReady(Exception):
    pass


class PagePreparationNotConfirmed(Exception):
    pass


class QueueFull(Exception):
    pass


class InvalidJobState(Exception):
    pass


class RetryLimitReached(Exception):
    pass


class LostLease(Exception):
    pass


class RegionReviewConflict(Exception):
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


@dataclass(frozen=True, slots=True)
class JobEvent:
    job_id: str
    sequence: int
    event_type: str
    state: str
    stage: str
    processed_count: int
    total_count: int
    attempt: int
    max_attempts: int
    cancellation_requested: bool
    error_code: str | None
    error_retryable: bool
    created_at: str

    @property
    def can_cancel(self) -> bool:
        return self.state in ACTIVE_STATES and not self.cancellation_requested

    @property
    def can_retry(self) -> bool:
        return (
            (self.state == "failed_retryable" and self.error_retryable)
            or self.state == "partial"
        ) and self.attempt < self.max_attempts


def _now() -> datetime:
    return datetime.now(UTC)


def _iso(value: datetime) -> str:
    return value.isoformat()


def _job(row: sqlite3.Row) -> Job:
    data = dict(row)
    data["error_retryable"] = bool(data["error_retryable"])
    return Job(**data)


def _job_event(row: sqlite3.Row) -> JobEvent:
    data = dict(row)
    data["cancellation_requested"] = bool(data["cancellation_requested"])
    data["error_retryable"] = bool(data["error_retryable"])
    return JobEvent(**data)


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
            """SELECT state,stage,processed_count,total_count,attempts,max_attempts,
                      cancellation_requested_at,error_code,error_retryable
               FROM recognition_jobs WHERE id=?""",
            (job_id,),
        ).fetchone()
        sequence = connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM job_events WHERE job_id=?", (job_id,)
        ).fetchone()[0]
        connection.execute(
            """INSERT INTO job_events(
                   job_id,sequence,event_type,state,stage,processed_count,total_count,attempt,
                   max_attempts,cancellation_requested,error_code,error_retryable,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                job_id,
                sequence,
                event_type,
                row["state"],
                row["stage"],
                row["processed_count"],
                row["total_count"],
                row["attempts"],
                row["max_attempts"],
                int(row["cancellation_requested_at"] is not None),
                error_code if error_code is not None else row["error_code"],
                row["error_retryable"],
                now,
            ),
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

    def list_events(
        self,
        owner_session_id: str,
        job_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 256,
    ) -> list[JobEvent]:
        if after_sequence < 0:
            raise ValueError("after_sequence must be non-negative")
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self.database.connect() as connection:
            owned = connection.execute(
                "SELECT 1 FROM recognition_jobs WHERE id=? AND owner_session_id=?",
                (job_id, owner_session_id),
            ).fetchone()
            if owned is None:
                raise JobNotFound(job_id)
            rows = connection.execute(
                """SELECT job_id,sequence,event_type,state,stage,processed_count,total_count,
                          attempt,max_attempts,cancellation_requested,error_code,error_retryable,created_at
                   FROM job_events
                   WHERE job_id=? AND sequence>?
                   ORDER BY sequence ASC
                   LIMIT ?""",
                (job_id, after_sequence, limit),
            ).fetchall()
        return [_job_event(row) for row in rows]

    def latest_event_sequence(self, owner_session_id: str, job_id: str) -> int:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT COALESCE(MAX(e.sequence), 0) AS latest_sequence
                   FROM recognition_jobs j
                   LEFT JOIN job_events e ON e.job_id=j.id
                   WHERE j.id=? AND j.owner_session_id=?
                   GROUP BY j.id""",
                (job_id, owner_session_id),
            ).fetchone()
        if row is None:
            raise JobNotFound(job_id)
        return int(row["latest_sequence"])

    def active_run_id(self, job_id: str) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id FROM recognition_runs WHERE job_id=? AND finished_at IS NULL ORDER BY started_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
        if row is None:
            raise InvalidJobState("recognition_run_missing")
        return str(row["id"])

    def set_run_metadata(self, job_id: str, worker_id: str, **metadata: object) -> None:
        allowed = {
            "model_manifest_sha256",
            "prepared_asset_id",
            "prepared_asset_sha256",
            "page_revision",
            "pipeline_manifest_sha256",
            "detector_name",
            "detector_version",
            "detector_config_json",
            "craft_detector_version",
            "craft_thresholds_json",
            "trocr_model_version",
            "rslora_adapter_version",
            "device",
            "dtype",
            "generation_parameters_json",
        }
        if not metadata or set(metadata) - allowed:
            raise ValueError("Invalid recognition run metadata")
        with self.database.transaction(immediate=True) as connection:
            job = connection.execute(
                "SELECT state,claimed_by FROM recognition_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if job is None or job["state"] != "running" or job["claimed_by"] != worker_id:
                raise LostLease(job_id)
            run = connection.execute(
                "SELECT id FROM recognition_runs WHERE job_id=? AND finished_at IS NULL ORDER BY started_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if run is None:
                raise InvalidJobState("recognition_run_missing")
            assignments = ",".join(f"{key}=?" for key in metadata)
            connection.execute(
                f"UPDATE recognition_runs SET {assignments} WHERE id=?",
                (*metadata.values(), run["id"]),
            )

    def record_model_readiness(
        self,
        worker_id: str,
        model_name: str,
        *,
        status: str,
        model_version: str | None = None,
        evidence: dict[str, object] | None = None,
        error_code: str | None = None,
    ) -> None:
        if model_name not in {"craft", "kraken", "trocr"} or status not in {"ready", "unavailable"}:
            raise ValueError("Invalid model readiness value")
        now = _iso(_now())
        payload = json.dumps(evidence, separators=(",", ":"), sort_keys=True) if evidence is not None else None
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO worker_model_readiness(worker_id,model_name,status,model_version,evidence_json,error_code,warmed_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?)
                   ON CONFLICT(worker_id,model_name) DO UPDATE SET
                   status=excluded.status,model_version=excluded.model_version,evidence_json=excluded.evidence_json,
                   error_code=excluded.error_code,warmed_at=excluded.warmed_at,updated_at=excluded.updated_at""",
                (worker_id, model_name, status, model_version, payload, error_code, now if status == "ready" else None, now),
            )

    def model_is_ready(self, model_name: str, *, stale_seconds: int) -> bool:
        cutoff = _iso(_now() - timedelta(seconds=stale_seconds))
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT 1 FROM worker_model_readiness r JOIN worker_heartbeats h ON h.worker_id=r.worker_id
                   WHERE r.model_name=? AND r.status='ready'
                     AND h.heartbeat_at>=? AND h.status IN ('idle','running') LIMIT 1""",
                (model_name, cutoff),
            ).fetchone()
        return row is not None

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
                """SELECT p.document_id,p.prepared_asset_id,p.preprocessing_recipe_hash,
                          p.preparation_confirmed_recipe_hash FROM pages p
                   JOIN documents d ON d.id=p.document_id
                   WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
                (page_id, owner_session_id),
            ).fetchone()
            if page is None:
                raise JobNotFound(page_id)
            if page["prepared_asset_id"] is None:
                raise PageNotReady(page_id)
            if (
                page["preprocessing_recipe_hash"] is None
                or page["preparation_confirmed_recipe_hash"] != page["preprocessing_recipe_hash"]
            ):
                raise PagePreparationNotConfirmed(page_id)
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
                """UPDATE recognition_jobs SET state=?,stage=stage,
                       claimed_by=NULL,lease_expires_at=NULL,heartbeat_at=NULL,error_code=?,error_retryable=?,
                       finished_at=?,updated_at=?,revision=revision+1 WHERE id=?""",
                    (state, code, retryable, finished, now, row["id"]),
                )
                if state in TERMINAL_STATES:
                    connection.execute(
                        "UPDATE recognition_runs SET finished_at=?,outcome='abandoned' WHERE job_id=? AND finished_at IS NULL",
                        (now, row["id"]),
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
            active_run = connection.execute(
                "SELECT id FROM recognition_runs WHERE job_id=? AND finished_at IS NULL ORDER BY started_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if active_run is None:
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

    def confirm_regions_and_resume(
        self,
        owner_session_id: str,
        page_id: str,
        *,
        expected_page_revision: int,
        job_id: str,
        expected_job_revision: int,
    ) -> tuple[int, Job]:
        """Atomically snapshot confirmed regions and queue the same durable job."""
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            page = connection.execute(
                """SELECT p.revision,p.document_id,p.prepared_asset_id,a.sha256 prepared_asset_sha256
                   FROM pages p JOIN documents d ON d.id=p.document_id
                   JOIN assets a ON a.id=p.prepared_asset_id AND a.state='committed'
                   WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
                (page_id, owner_session_id),
            ).fetchone()
            if page is None:
                raise JobNotFound(page_id)
            job = connection.execute(
                "SELECT * FROM recognition_jobs WHERE id=? AND page_id=? AND owner_session_id=?",
                (job_id, page_id, owner_session_id),
            ).fetchone()
            if job is None:
                raise JobNotFound(job_id)
            if page["revision"] != expected_page_revision or job["revision"] != expected_job_revision:
                raise RegionReviewConflict("revision_conflict")
            if job["state"] != "awaiting_region_review" or job["stage"] != "awaiting_region_review":
                raise RegionReviewConflict("job_not_awaiting_region_review")
            run = connection.execute(
                "SELECT id FROM recognition_runs WHERE job_id=? AND finished_at IS NULL ORDER BY started_at DESC LIMIT 1",
                (job_id,),
            ).fetchone()
            if run is None:
                raise RegionReviewConflict("recognition_run_missing")
            prior_snapshot = connection.execute(
                "SELECT 1 FROM recognition_run_regions WHERE recognition_run_id=? LIMIT 1", (run["id"],)
            ).fetchone()
            if prior_snapshot is not None:
                raise RegionReviewConflict("regions_already_confirmed")
            regions = connection.execute(
                """SELECT id,polygon_json,reading_order,source,flags_json,detector_version,detector_score
                   FROM recognition_regions WHERE page_id=? ORDER BY reading_order,id""",
                (page_id,),
            ).fetchall()
            confirmed_revision = expected_page_revision + 1
            connection.execute(
                """UPDATE pages SET regions_confirmed_revision=?,regions_confirmed_at=?,revision=?,updated_at=?
                   WHERE id=?""",
                (confirmed_revision, now, confirmed_revision, now, page_id),
            )
            for region in regions:
                connection.execute(
                    """INSERT INTO recognition_run_regions(
                           id,recognition_run_id,page_id,source_region_id,polygon_json,reading_order,source,
                           flags_json,detector_version,detector_score,page_revision,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        str(uuid4()), run["id"], page_id, region["id"], region["polygon_json"], region["reading_order"],
                        region["source"], region["flags_json"], region["detector_version"], region["detector_score"],
                        confirmed_revision, now,
                    ),
                )
            connection.execute(
                """UPDATE recognition_runs SET prepared_asset_id=?,prepared_asset_sha256=?,page_revision=?
                   WHERE id=?""",
                (page["prepared_asset_id"], page["prepared_asset_sha256"], confirmed_revision, run["id"]),
            )
            connection.execute(
                """UPDATE recognition_jobs SET state='queued',stage='recognizing_lines',processed_count=0,total_count=?,
                   available_at=?,claimed_by=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?,revision=revision+1
                   WHERE id=?""",
                (len(regions), now, now, job_id),
            )
            self._event(connection, job_id, "regions_confirmed", now)
        return confirmed_revision, self.get(owner_session_id, job_id)

    def request_cancel(self, owner_session_id: str, job_id: str) -> Job:
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT state FROM recognition_jobs WHERE id=? AND owner_session_id=?", (job_id, owner_session_id)).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            if row["state"] in {"queued", "awaiting_region_review"}:
                connection.execute("UPDATE recognition_jobs SET state='cancelled',finished_at=?,updated_at=?,revision=revision+1 WHERE id=?", (now, now, job_id))
                connection.execute(
                    "UPDATE recognition_runs SET finished_at=?,outcome='cancelled' WHERE job_id=? AND finished_at IS NULL",
                    (now, job_id),
                )
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

    def advance_progress(self, job_id: str, worker_id: str, stage: str, *, processed_count: int, total_count: int) -> None:
        if stage not in JOB_STAGES or processed_count < 0 or total_count < 0 or processed_count > total_count:
            raise ValueError("Invalid progress counters")
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT state,claimed_by,processed_count,total_count FROM recognition_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None or row["state"] != "running" or row["claimed_by"] != worker_id:
                raise LostLease(job_id)
            if processed_count < row["processed_count"] or (total_count and row["total_count"] and total_count < row["total_count"]):
                raise InvalidJobState("progress must be monotonic")
            connection.execute(
                "UPDATE recognition_jobs SET stage=?,processed_count=?,total_count=?,updated_at=?,revision=revision+1 WHERE id=?",
                (stage, processed_count, total_count, now, job_id),
            )
            self._event(connection, job_id, "stage_progress", now)

    def pause_for_region_review(self, job_id: str, worker_id: str) -> Job:
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute(
                "SELECT cancellation_requested_at FROM recognition_jobs WHERE id=? AND state='running' AND claimed_by=?",
                (job_id, worker_id),
            ).fetchone()
            if row is None:
                raise LostLease(job_id)
            if row["cancellation_requested_at"] is not None:
                raise InvalidJobState("job_cancelled")
            connection.execute(
                """UPDATE recognition_jobs SET state='awaiting_region_review',stage='awaiting_region_review',
                   claimed_by=NULL,lease_expires_at=NULL,heartbeat_at=NULL,updated_at=?,revision=revision+1 WHERE id=?""",
                (now, job_id),
            )
            connection.execute(
                "DELETE FROM pipeline_locks WHERE resource='gpu_pipeline' AND job_id=? AND worker_id=?",
                (job_id, worker_id),
            )
            self._event(connection, job_id, "awaiting_region_review", now)
        return self.get_internal(job_id)

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
            if state not in {"partial", "failed_retryable"}:
                connection.execute(
                    "UPDATE recognition_runs SET finished_at=?,outcome=? WHERE job_id=? AND finished_at IS NULL",
                    (now, state, job_id),
                )
            connection.execute("DELETE FROM pipeline_locks WHERE resource='gpu_pipeline' AND job_id=? AND worker_id=?", (job_id, worker_id))
            self._event(connection, job_id, state, now, error_code)
        return self.get_internal(job_id)

    def complete_manual_fallback(self, owner_session_id: str, job_id: str, recognition_run_id: str) -> Job:
        """Close a partial job only after every immutable run region has raw text."""
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            job = connection.execute(
                "SELECT state FROM recognition_jobs WHERE id=? AND owner_session_id=?",
                (job_id, owner_session_id),
            ).fetchone()
            if job is None:
                raise JobNotFound(job_id)
            if job["state"] != "partial":
                raise InvalidJobState(str(job["state"]))
            run = connection.execute(
                "SELECT id FROM recognition_runs WHERE id=? AND job_id=? AND finished_at IS NULL",
                (recognition_run_id, job_id),
            ).fetchone()
            if run is None:
                raise InvalidJobState("recognition_run_not_active")
            pending = connection.execute(
                """WITH ranked AS (
                     SELECT run_region_id,state,
                            ROW_NUMBER() OVER(PARTITION BY run_region_id ORDER BY line_attempt DESC) AS rank
                     FROM recognition_line_results WHERE recognition_run_id=?
                   )
                   SELECT COUNT(*) FROM recognition_run_regions rr
                   LEFT JOIN ranked lr ON lr.run_region_id=rr.id AND lr.rank=1
                   WHERE rr.recognition_run_id=? AND (lr.state IS NULL OR lr.state!='completed')""",
                (recognition_run_id, recognition_run_id),
            ).fetchone()[0]
            if pending:
                raise InvalidJobState("manual_fallback_incomplete")
            connection.execute(
                """UPDATE recognition_jobs SET state='completed',stage='ready_for_review',error_code=NULL,
                   error_retryable=0,claimed_by=NULL,lease_expires_at=NULL,heartbeat_at=NULL,
                   finished_at=?,updated_at=?,revision=revision+1 WHERE id=?""",
                (now, now, job_id),
            )
            connection.execute(
                "UPDATE recognition_runs SET finished_at=?,outcome='completed' WHERE id=?",
                (now, recognition_run_id),
            )
            self._event(connection, job_id, "manual_fallback_completed", now)
        return self.get(owner_session_id, job_id)

    def retry(self, owner_session_id: str, job_id: str) -> Job:
        now = _iso(_now())
        with self.database.transaction(immediate=True) as connection:
            row = connection.execute("SELECT state,stage,attempts,max_attempts FROM recognition_jobs WHERE id=? AND owner_session_id=?", (job_id, owner_session_id)).fetchone()
            if row is None:
                raise JobNotFound(job_id)
            if row["attempts"] >= row["max_attempts"]:
                raise RetryLimitReached(job_id)
            if row["state"] == "queued":
                return self.get(owner_session_id, job_id)
            if row["state"] not in {"failed_retryable", "partial"}:
                raise InvalidJobState(row["state"])
            stage = row["stage"]
            connection.execute(
                """UPDATE recognition_jobs SET state='queued',stage=?,available_at=?,claimed_by=NULL,
                   lease_expires_at=NULL,heartbeat_at=NULL,cancellation_requested_at=NULL,error_code=NULL,
                   error_retryable=0,finished_at=NULL,updated_at=?,revision=revision+1 WHERE id=?""",
                (stage, now, now, job_id),
            )
            self._event(connection, job_id, "retried", now)
        return self.get(owner_session_id, job_id)
