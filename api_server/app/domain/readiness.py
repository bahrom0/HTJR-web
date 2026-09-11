from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.core.database import Database
from app.core.settings import Settings
from app.ml.craft import craft_status
from app.ml.trocr_runtime import inspect_trocr_artifacts
from app.repositories.jobs import JobRepository


@dataclass(frozen=True, slots=True)
class Readiness:
    is_ready: bool
    code: str


class ReadinessService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self._jobs = JobRepository(database)
        self._stale_seconds = settings.worker_lease_seconds
        self._craft_enabled = settings.craft_enabled
        self._trocr_adapter_mode = settings.trocr_adapter_mode
        self._ocr_provider = settings.ocr_provider
        self._gemini_mode = settings.gemini_mode

    def check(self) -> Readiness:
        if self._jobs.worker_is_fresh(stale_seconds=self._stale_seconds):
            return Readiness(is_ready=True, code="ready")
        return Readiness(is_ready=False, code="worker_unavailable")

    def detector_check(self) -> Readiness:
        worker = self.check()
        if not worker.is_ready:
            return worker
        detector_name = (
            "gemini_openrouter"
            if self._ocr_provider == "gemini" and self._gemini_mode == "page"
            else "craft" if self._craft_enabled else "kraken"
        )
        if detector_name == "craft":
            detector = craft_status()
            if not detector.ready:
                return Readiness(is_ready=False, code=detector.code)
        if not self._jobs.model_is_ready(detector_name, stale_seconds=self._stale_seconds):
            return Readiness(is_ready=False, code=f"{detector_name}_warmup_unavailable")
        return Readiness(is_ready=True, code="ready")

    def pipeline_check(self) -> Readiness:
        detector = self.detector_check()
        if not detector.is_ready:
            return detector
        if self._ocr_provider == "gemini":
            if not self._jobs.model_is_ready("gemini_openrouter", stale_seconds=self._stale_seconds):
                return Readiness(is_ready=False, code="gemini_openrouter_warmup_unavailable")
            return Readiness(is_ready=True, code="ready")
        models_root = Path(__file__).resolve().parents[2] / "models"
        trocr = inspect_trocr_artifacts(models_root, adapter_mode=self._trocr_adapter_mode)
        if not trocr.ready:
            return Readiness(is_ready=False, code=trocr.code)
        if not self._jobs.model_is_ready("trocr", stale_seconds=self._stale_seconds):
            return Readiness(is_ready=False, code="trocr_warmup_unavailable")
        return Readiness(is_ready=True, code="ready")
