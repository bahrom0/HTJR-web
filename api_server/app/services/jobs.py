from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Callable, Mapping

from app.repositories.jobs import Job, JobRepository, LostLease

logger = logging.getLogger(__name__)


class JobCancelled(Exception):
    pass


class RetryableJobError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


class TerminalJobError(Exception):
    def __init__(self, code: str) -> None:
        self.code = code


@dataclass(frozen=True, slots=True)
class JobResult:
    state: str = "completed"

    def __post_init__(self) -> None:
        if self.state not in {"completed", "partial", "awaiting_region_review"}:
            raise ValueError("A handler result must be completed, partial, or awaiting_region_review")


class JobContext:
    def __init__(self, repository: JobRepository, job: Job, worker_id: str, lease_seconds: int) -> None:
        self.repository = repository
        self.job = job
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds

    @property
    def completed_stages(self) -> frozenset[str]:
        return self.repository.completed_stages(self.job.id)

    def checkpoint(self) -> None:
        if self.repository.cancellation_requested(self.job.id, self.worker_id):
            raise JobCancelled
        self.repository.heartbeat(self.job.id, self.worker_id, lease_seconds=self.lease_seconds)

    def complete_stage(self, stage: str, *, processed_count: int, total_count: int, partial: bool = False) -> None:
        self.checkpoint()
        self.repository.save_stage(
            self.job.id,
            self.worker_id,
            stage,
            processed_count=processed_count,
            total_count=total_count,
            outcome="partial" if partial else "completed",
        )

    def advance_progress(self, stage: str, *, processed_count: int, total_count: int) -> None:
        self.checkpoint()
        self.repository.advance_progress(
            self.job.id,
            self.worker_id,
            stage,
            processed_count=processed_count,
            total_count=total_count,
        )


JobHandler = Callable[[JobContext], JobResult | None]


class WorkerService:
    def __init__(self, repository: JobRepository, *, worker_id: str, lease_seconds: int, heartbeat_seconds: float | None = None, handlers: Mapping[str, JobHandler] | None = None) -> None:
        self.repository = repository
        self.worker_id = worker_id
        self.lease_seconds = lease_seconds
        self.heartbeat_seconds = heartbeat_seconds or lease_seconds / 3
        self.handlers = dict(handlers or {})
        self.started_at = datetime.now(UTC).isoformat()

    def _run_handler_with_heartbeat(self, context: JobContext, handler: JobHandler) -> JobResult | None:
        stop = threading.Event()
        lease_lost = threading.Event()

        def maintain_lease() -> None:
            interval = max(0.1, min(self.heartbeat_seconds, self.lease_seconds / 3))
            while not stop.wait(interval):
                try:
                    self.repository.heartbeat(context.job.id, self.worker_id, lease_seconds=self.lease_seconds)
                    self.repository.record_worker_heartbeat(
                        self.worker_id, status="running", current_job_id=context.job.id, started_at=self.started_at
                    )
                except LostLease:
                    lease_lost.set()
                    return

        keeper = threading.Thread(target=maintain_lease, name="job-lease-heartbeat", daemon=True)
        keeper.start()
        try:
            result = handler(context)
        finally:
            stop.set()
            keeper.join(timeout=max(1.0, self.lease_seconds / 2))
        if lease_lost.is_set():
            raise LostLease(context.job.id)
        return result

    def run_once(self) -> bool:
        self.repository.record_worker_heartbeat(self.worker_id, status="idle", current_job_id=None, started_at=self.started_at)
        job = self.repository.claim(self.worker_id, lease_seconds=self.lease_seconds)
        if job is None:
            return False
        self.repository.record_worker_heartbeat(self.worker_id, status="running", current_job_id=job.id, started_at=self.started_at)
        context = JobContext(self.repository, job, self.worker_id, self.lease_seconds)
        try:
            context.checkpoint()
            handler = self.handlers.get(job.job_kind)
            if handler is None:
                raise RetryableJobError("pipeline_not_available")
            result = self._run_handler_with_heartbeat(context, handler) or JobResult()
            if result.state == "awaiting_region_review":
                self.repository.pause_for_region_review(job.id, self.worker_id)
            else:
                context.checkpoint()
                self.repository.finish(job.id, self.worker_id, result.state)
        except JobCancelled:
            self.repository.finish(job.id, self.worker_id, "cancelled")
        except RetryableJobError as error:
            self.repository.finish(job.id, self.worker_id, "failed_retryable", error_code=error.code)
        except TerminalJobError as error:
            self.repository.finish(job.id, self.worker_id, "failed_terminal", error_code=error.code)
        except LostLease:
            logger.warning("worker_lost_job_lease worker_id=%s job_id=%s", self.worker_id, job.id)
        except Exception as error:
            logger.error("worker_job_failed worker_id=%s job_id=%s error_type=%s", self.worker_id, job.id, type(error).__name__)
            try:
                self.repository.finish(job.id, self.worker_id, "failed_retryable", error_code="worker_stage_crashed")
            except LostLease:
                logger.warning("worker_lost_job_lease_after_failure worker_id=%s job_id=%s", self.worker_id, job.id)
        finally:
            self.repository.record_worker_heartbeat(self.worker_id, status="idle", current_job_id=None, started_at=self.started_at)
        return True

    def run_forever(self, stop_event: threading.Event, *, poll_seconds: float) -> None:
        try:
            while not stop_event.is_set():
                worked = self.run_once()
                if not worked:
                    stop_event.wait(poll_seconds)
        finally:
            self.repository.record_worker_heartbeat(self.worker_id, status="stopping", current_job_id=None, started_at=self.started_at)
