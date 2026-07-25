from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core.database import Database
from app.core.storage import FileStorage
from app.services.jobs import JobResult, RetryableJobError, TerminalJobError
from app.worker import main as worker_main


@dataclass(frozen=True)
class _Job:
    id: str = "job-123"


@dataclass(frozen=True)
class _Context:
    job: _Job = _Job()
    worker_id: str = "worker-123"
    lease_seconds: int = 90


def _paths(tmp_path: Path) -> tuple[Database, FileStorage, Path]:
    return Database(tmp_path / "studio.sqlite3"), FileStorage(tmp_path / "assets"), tmp_path / "models"


def test_process_protocol_uses_only_the_final_structured_line() -> None:
    assert worker_main._json_protocol_output("library warning\n{\"status\": \"ok\"}\n") == {"status": "ok"}
    assert worker_main._json_protocol_output("not-json") is None


def test_phase_process_returns_only_supported_durable_result(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database, storage, models = _paths(tmp_path)
    monkeypatch.setattr(
        worker_main.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=0, stdout='{"status":"ok","state":"awaiting_region_review"}'),
    )

    result = worker_main._run_phase_subprocess(_Context(), database=database, storage=storage, models_root=models)

    assert result == JobResult("awaiting_region_review")


def test_phase_process_maps_sanitized_child_failure(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    database, storage, models = _paths(tmp_path)
    monkeypatch.setattr(
        worker_main.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout='{"status":"terminal","code":"recognition_input_missing"}'),
    )

    with pytest.raises(TerminalJobError, match="recognition_input_missing"):
        worker_main._run_phase_subprocess(_Context(), database=database, storage=storage, models_root=models)

    monkeypatch.setattr(
        worker_main.subprocess,
        "run",
        lambda *args, **kwargs: SimpleNamespace(returncode=1, stdout=""),
    )
    with pytest.raises(RetryableJobError, match="worker_phase_crashed"):
        worker_main._run_phase_subprocess(_Context(), database=database, storage=storage, models_root=models)
