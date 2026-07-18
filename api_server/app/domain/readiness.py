from __future__ import annotations

from dataclasses import dataclass

from app.core.database import Database
from app.core.settings import Settings
from app.repositories.jobs import JobRepository


@dataclass(frozen=True, slots=True)
class Readiness:
    is_ready: bool
    code: str


class ReadinessService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._jobs = JobRepository(database)
        self._stale_seconds = settings.worker_lease_seconds

    def check(self) -> Readiness:
        if self._jobs.worker_is_fresh(stale_seconds=self._stale_seconds):
            return Readiness(is_ready=True, code="ready")
        return Readiness(is_ready=False, code="worker_unavailable")
