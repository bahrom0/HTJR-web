from __future__ import annotations

import threading
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest
from dataclasses import replace
from fastapi.testclient import TestClient

from app.core.database import Database
from app.core.settings import settings
from app.domain.readiness import ReadinessService
from app.repositories.jobs import JobRepository, QueueFull, RetryLimitReached
from app.services.jobs import JobResult, RetryableJobError, WorkerService


def _seed(database: Database, *, owner: str = "owner-1", page_count: int = 1) -> tuple[str, list[str]]:
    now = datetime.now(UTC).isoformat()
    document_id = str(uuid4())
    pages: list[str] = []
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO access_sessions(id,token_hash,csrf_hash,created_at,expires_at,last_seen_at) VALUES (?,?,?,?,?,?)",
            (owner, f"token-{owner}".encode(), f"csrf-{owner}".encode(), now, (datetime.now(UTC) + timedelta(hours=1)).isoformat(), now),
        )
        connection.execute("INSERT INTO documents(id,owner_session_id,title,created_at,updated_at) VALUES (?,?,?,?,?)", (document_id, owner, "Test", now, now))
        for index in range(page_count):
            page_id, source_id, prepared_id = str(uuid4()), str(uuid4()), str(uuid4())
            connection.execute(
                "INSERT INTO assets(id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,committed_at,kind,width,height) VALUES (?,?,?,?,?,1,'image/png','committed',?,?,'original',10,10)",
                (source_id, owner, document_id, f"source-{page_id}", "a" * 64, now, now),
            )
            connection.execute(
                "INSERT INTO assets(id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,committed_at,kind,width,height,parent_asset_id) VALUES (?,?,?,?,?,1,'image/png','committed',?,?,'prepared',10,10,?)",
                (prepared_id, owner, document_id, f"prepared-{page_id}", "b" * 64, now, now, source_id),
            )
            connection.execute(
                """INSERT INTO pages(
                       id,document_id,source_asset_id,page_index,created_at,updated_at,prepared_asset_id,
                       preprocessing_recipe_hash,preparation_confirmed_recipe_hash)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (page_id, document_id, source_id, index, now, now, prepared_id, "a" * 64, "a" * 64),
            )
            pages.append(page_id)
    return owner, pages


@pytest.fixture
def jobs(tmp_path: Path) -> tuple[Database, JobRepository, str, list[str]]:
    database = Database(tmp_path / "jobs.sqlite3")
    database.migrate()
    owner, pages = _seed(database, page_count=4)
    return database, JobRepository(database), owner, pages


def _enqueue(repository: JobRepository, owner: str, page: str, key: str, *, priority: int = 0, capacity: int = 20, max_attempts: int = 3):
    return repository.enqueue(owner, page, key, priority=priority, capacity=capacity, max_attempts=max_attempts)[0]


def test_idempotency_bounded_queue_priority_and_fifo(jobs) -> None:
    _, repository, owner, pages = jobs
    first, duplicate = repository.enqueue(owner, pages[0], "same-key-0000001", priority=0, capacity=3, max_attempts=3)
    repeated, is_duplicate = repository.enqueue(owner, pages[0], "same-key-0000001", priority=10, capacity=3, max_attempts=3)
    assert duplicate is False and is_duplicate is True and repeated.id == first.id
    second = _enqueue(repository, owner, pages[1], "second-key-000001", priority=5, capacity=3)
    third = _enqueue(repository, owner, pages[2], "third-key-0000001", priority=5, capacity=3)
    with pytest.raises(QueueFull):
        _enqueue(repository, owner, pages[3], "fourth-key-000001", capacity=3)
    assert repository.claim("w1", lease_seconds=30).id == second.id
    repository.finish(second.id, "w1", "completed")
    assert repository.claim("w1", lease_seconds=30).id == third.id


def test_two_workers_cannot_claim_same_or_parallel_job(jobs) -> None:
    _, repository, owner, pages = jobs
    expected = _enqueue(repository, owner, pages[0], "race-key-00000001")
    results: list[str | None] = []
    barrier = threading.Barrier(2)

    def claim(worker: str) -> None:
        barrier.wait()
        item = repository.claim(worker, lease_seconds=30)
        results.append(item.id if item else None)

    threads = [threading.Thread(target=claim, args=(f"w{i}",)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert results.count(expected.id) == 1
    assert results.count(None) == 1


def test_stage_survives_crash_and_restart_then_retry(jobs) -> None:
    database, repository, owner, pages = jobs
    job = _enqueue(repository, owner, pages[0], "crash-key-0000001")

    def crashing(context):
        context.complete_stage("detecting_regions", processed_count=2, total_count=2)
        raise RuntimeError("simulated crash")

    WorkerService(repository, worker_id="w1", lease_seconds=30, handlers={"page_recognition": crashing}).run_once()
    failed = repository.get(owner, job.id)
    assert failed.state == "failed_retryable"
    assert repository.completed_stages(job.id) == {"detecting_regions"}
    repository.retry(owner, job.id)

    resumed: list[frozenset[str]] = []

    def completing(context):
        resumed.append(context.completed_stages)
        context.complete_stage("assembling", processed_count=1, total_count=1)
        return JobResult("completed")

    restarted = JobRepository(Database(database.path))
    WorkerService(restarted, worker_id="w2", lease_seconds=30, handlers={"page_recognition": completing}).run_once()
    assert resumed == [{"detecting_regions"}]
    assert restarted.get(owner, job.id).state == "completed"


def test_cancel_and_retry_limit(jobs) -> None:
    _, repository, owner, pages = jobs
    queued = _enqueue(repository, owner, pages[0], "cancel-key-000001")
    assert repository.request_cancel(owner, queued.id).state == "cancelled"
    retrying = _enqueue(repository, owner, pages[1], "retry-key-0000001", max_attempts=1)

    def fail(_context):
        raise RetryableJobError("temporary_failure")

    WorkerService(repository, worker_id="w", lease_seconds=30, handlers={"page_recognition": fail}).run_once()
    assert repository.get(owner, retrying.id).state == "failed_terminal"
    with pytest.raises(RetryLimitReached):
        repository.retry(owner, retrying.id)


def test_stale_claim_recovers_after_restart(jobs) -> None:
    database, repository, owner, pages = jobs
    job = _enqueue(repository, owner, pages[0], "stale-key-0000001")
    claimed = repository.claim("dead-worker", lease_seconds=30)
    assert claimed and claimed.id == job.id
    future = datetime.now(UTC) + timedelta(seconds=31)
    restarted = JobRepository(Database(database.path))
    assert restarted.recover_stale(at=future) == 1
    assert restarted.get(owner, job.id).state == "queued"
    assert restarted.claim("new-worker", lease_seconds=30, at=future).id == job.id


def test_running_cancellation_wins_at_worker_checkpoint(jobs) -> None:
    _, repository, owner, pages = jobs
    job = _enqueue(repository, owner, pages[0], "running-cancel-001")

    def cancel_during_run(context):
        repository.request_cancel(owner, context.job.id)
        context.checkpoint()

    WorkerService(repository, worker_id="w", lease_seconds=30, handlers={"page_recognition": cancel_during_run}).run_once()
    assert repository.get(owner, job.id).state == "cancelled"


def test_unregistered_production_pipeline_is_typed_failure(jobs) -> None:
    _, repository, owner, pages = jobs
    job = _enqueue(repository, owner, pages[0], "missing-pipe-0001")
    WorkerService(repository, worker_id="w", lease_seconds=30, handlers={}).run_once()
    failed = repository.get(owner, job.id)
    assert failed.state == "failed_retryable"
    assert failed.error_code == "pipeline_not_available"


def test_partial_result_and_automatic_lease_heartbeat(jobs) -> None:
    _, repository, owner, pages = jobs
    job = _enqueue(repository, owner, pages[0], "partial-key-000001")

    def slow_partial(context):
        time.sleep(0.45)
        context.complete_stage("recognizing_lines", processed_count=2, total_count=3, partial=True)
        return JobResult("partial")

    WorkerService(repository, worker_id="w", lease_seconds=1, handlers={"page_recognition": slow_partial}).run_once()
    result = repository.get(owner, job.id)
    assert result.state == "partial"
    assert (result.processed_count, result.total_count) == (2, 3)


def test_readiness_comes_from_persisted_worker_heartbeat(jobs) -> None:
    database, repository, _, _ = jobs
    configured = replace(settings, database_path=database.path, worker_lease_seconds=90)
    readiness = ReadinessService(database, configured)
    assert readiness.check().is_ready is False
    repository.record_worker_heartbeat("w", status="idle", current_job_id=None, started_at=datetime.now(UTC).isoformat())
    restarted_readiness = ReadinessService(Database(database.path), configured)
    assert restarted_readiness.check().is_ready is True


def test_job_api_enforces_csrf_idempotency_and_ownership(tmp_path: Path, monkeypatch) -> None:
    configured = replace(
        settings,
        database_path=tmp_path / "api.sqlite3",
        storage_root=tmp_path / "assets",
        access_code_enabled=True,
    )
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as client:
        code, _ = client.app.state.access.issue_code("owner-one")
        exchange = client.post("/api/v1/access/exchange-code", json={"code": code})
        csrf = exchange.json()["csrf_token"]
        owner = client.app.state.access.authenticate(client.cookies.get(configured.cookie_name))["id"]
        _, pages = _seed(client.app.state.database, owner=owner, page_count=1)
        page = pages[0]
        denied = client.post(f"/api/v1/pages/{page}/recognition-jobs", json={}, headers={"Idempotency-Key": "api-job-key-00001"})
        assert denied.status_code == 401
        created = client.post(f"/api/v1/pages/{page}/recognition-jobs", json={}, headers={"Idempotency-Key": "api-job-key-00001", "X-CSRF-Token": csrf})
        assert created.status_code == 201 and created.json()["state"] == "queued"
        duplicate = client.post(f"/api/v1/pages/{page}/recognition-jobs", json={"priority": 10}, headers={"Idempotency-Key": "api-job-key-00001", "X-CSRF-Token": csrf})
        assert duplicate.status_code == 201 and duplicate.json()["duplicate"] is True
        job_id = created.json()["id"]

        other_code, _ = client.app.state.access.issue_code("owner-two")
        other_exchange = client.post("/api/v1/access/exchange-code", json={"code": other_code})
        assert client.get(f"/api/v1/jobs/{job_id}").status_code == 404
        client.cookies.set(configured.cookie_name, exchange.cookies.get(configured.cookie_name))
        cancelled = client.post(f"/api/v1/jobs/{job_id}/cancel", headers={"X-CSRF-Token": csrf})
        assert cancelled.status_code == 200 and cancelled.json()["state"] == "cancelled"
