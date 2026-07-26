from __future__ import annotations

import asyncio
import json
import shutil
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api.events import encode_job_event, stream_job_events
from app.core.database import Database
from app.core.settings import settings
from app.repositories.jobs import JobNotFound, JobRepository
from app.services.access import AccessService


def _seed_page(database: Database, owner: str) -> str:
    now = datetime.now(UTC).isoformat()
    document_id = str(uuid4())
    page_id = str(uuid4())
    source_id = str(uuid4())
    prepared_id = str(uuid4())
    with database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO documents(id,owner_session_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
            (document_id, owner, "Event test", now, now),
        )
        connection.execute(
            """INSERT INTO assets(
                   id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,
                   state,created_at,committed_at,kind,width,height)
               VALUES (?,?,?,?,?,1,'image/png','committed',?,?,'original',10,10)""",
            (source_id, owner, document_id, f"source-{page_id}", "a" * 64, now, now),
        )
        connection.execute(
            """INSERT INTO assets(
                   id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,
                   state,created_at,committed_at,kind,width,height,parent_asset_id)
               VALUES (?,?,?,?,?,1,'image/png','committed',?,?,'prepared',10,10,?)""",
            (prepared_id, owner, document_id, f"prepared-{page_id}", "b" * 64, now, now, source_id),
        )
        page_columns = {row[1] for row in connection.execute("PRAGMA table_info(pages)")}
        if "preparation_confirmed_recipe_hash" in page_columns:
            connection.execute(
                """INSERT INTO pages(
                       id,document_id,source_asset_id,page_index,created_at,updated_at,prepared_asset_id,
                       preprocessing_recipe_hash,preparation_confirmed_recipe_hash)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (page_id, document_id, source_id, 0, now, now, prepared_id, "a" * 64, "a" * 64),
            )
        else:
            connection.execute(
                "INSERT INTO pages(id,document_id,source_asset_id,page_index,created_at,updated_at,prepared_asset_id) "
                "VALUES (?,?,?,?,?,?,?)",
                (page_id, document_id, source_id, 0, now, now, prepared_id),
            )
    return page_id


def _access(database: Database, configured_settings, label: str) -> tuple[AccessService, str, str]:
    service = AccessService(database, configured_settings)
    code, _ = service.issue_code(label)
    grant = service.exchange(code, label)
    return service, grant.session_id, grant.token


def test_persisted_event_projection_is_ordered_owned_and_restart_replayable(tmp_path: Path) -> None:
    database = Database(tmp_path / "events.sqlite3")
    database.migrate()
    configured = replace(settings, database_path=database.path, storage_root=tmp_path / "assets")
    _, owner, _ = _access(database, configured, "owner")
    _, other, _ = _access(database, configured, "other")
    page_id = _seed_page(database, owner)
    repository = JobRepository(database)
    job, _ = repository.enqueue(
        owner,
        page_id,
        "event-stream-key-0001",
        priority=0,
        capacity=10,
        max_attempts=3,
    )
    duplicate, was_duplicate = repository.enqueue(
        owner,
        page_id,
        "event-stream-key-0001",
        priority=10,
        capacity=10,
        max_attempts=3,
    )
    assert was_duplicate is True and duplicate.id == job.id
    assert [event.sequence for event in repository.list_events(owner, job.id)] == [1]
    repository.claim("worker", lease_seconds=30)
    repository.request_cancel(owner, job.id)
    repository.finish(job.id, "worker", "cancelled")

    events = repository.list_events(owner, job.id)
    assert [event.sequence for event in events] == [1, 2, 3, 4]
    assert [event.event_type for event in events] == [
        "queued",
        "claimed",
        "cancellation_requested",
        "cancelled",
    ]
    assert events[0].can_cancel is True
    assert events[2].cancellation_requested is True and events[2].can_cancel is False
    assert events[3].state == "cancelled" and events[3].can_retry is False
    assert [event.sequence for event in repository.list_events(owner, job.id, after_sequence=2)] == [3, 4]
    with pytest.raises(JobNotFound):
        repository.list_events(other, job.id)

    restarted = JobRepository(Database(database.path))
    replay = restarted.list_events(owner, job.id, after_sequence=1)
    assert [event.sequence for event in replay] == [2, 3, 4]
    encoded = encode_job_event(replay[-1]).decode("utf-8")
    assert encoded.startswith("id: 4\nevent: job\ndata: ")
    payload = json.loads(next(line[6:] for line in encoded.splitlines() if line.startswith("data: ")))
    assert payload["job_id"] == job.id
    assert set(payload) == {
        "job_id",
        "sequence",
        "event_type",
        "state",
        "stage",
        "processed_count",
        "total_count",
        "attempt",
        "max_attempts",
        "cancellation_requested",
        "error_code",
        "error_retryable",
        "can_cancel",
        "can_retry",
        "created_at",
    }
    assert document_id_not_exposed(payload)


def document_id_not_exposed(payload: dict[str, object]) -> bool:
    return "document_id" not in payload and "page_id" not in payload and "text" not in payload


def test_event_projection_migration_upgrades_existing_database(tmp_path: Path) -> None:
    migrations = Path(__file__).parents[1] / "migrations"
    old_migrations = tmp_path / "old-migrations"
    old_migrations.mkdir()
    for source in sorted(migrations.glob("00[1-3]_*.sql")):
        shutil.copyfile(source, old_migrations / source.name)

    database_path = tmp_path / "existing.sqlite3"
    old_database = Database(database_path, migrations_dir=old_migrations)
    old_database.migrate()
    configured = replace(settings, database_path=database_path, storage_root=tmp_path / "assets")
    _, owner, _ = _access(old_database, configured, "owner")
    page_id = _seed_page(old_database, owner)
    now = datetime.now(UTC).isoformat()
    document_id = None
    with old_database.transaction(immediate=True) as connection:
        document_id = connection.execute("SELECT document_id FROM pages WHERE id=?", (page_id,)).fetchone()[0]
        job_id = str(uuid4())
        connection.execute(
            """INSERT INTO recognition_jobs(
                   id,owner_session_id,document_id,page_id,state,stage,attempts,max_attempts,
                   available_at,created_at,updated_at)
               VALUES (?,?,?,?, 'failed_retryable','recognizing_lines',1,5,?,?,?)""",
            (job_id, owner, document_id, page_id, now, now, now),
        )
        connection.execute(
            """INSERT INTO job_events(
                   job_id,sequence,event_type,state,stage,processed_count,total_count,attempt,error_code,created_at)
               VALUES (?,1,'failed_retryable','failed_retryable','recognizing_lines',2,3,1,'temporary_failure',?)""",
            (job_id, now),
        )

    upgraded = Database(database_path)
    upgraded.migrate()
    event = JobRepository(upgraded).list_events(owner, job_id)[0]
    assert event.max_attempts == 5
    assert event.error_retryable is True
    assert event.can_retry is True
    with upgraded.connect() as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version='004_job_event_projection.sql'"
        ).fetchone()[0] == 1


def test_retry_projection_comes_only_from_persisted_state(tmp_path: Path) -> None:
    database = Database(tmp_path / "retry-events.sqlite3")
    database.migrate()
    configured = replace(settings, database_path=database.path, storage_root=tmp_path / "assets")
    service, owner, token = _access(database, configured, "owner")
    page_id = _seed_page(database, owner)
    repository = JobRepository(database)
    job, _ = repository.enqueue(
        owner,
        page_id,
        "retry-event-key-0001",
        priority=0,
        capacity=10,
        max_attempts=3,
    )
    repository.claim("worker", lease_seconds=30)
    repository.finish(job.id, "worker", "failed_retryable", error_code="temporary_pipeline_failure")

    failed = repository.list_events(owner, job.id)[-1]
    assert failed.state == "failed_retryable"
    assert failed.error_code == "temporary_pipeline_failure"
    assert failed.error_retryable is True and failed.can_retry is True

    class ConnectedRequest:
        app = SimpleNamespace(state=SimpleNamespace(jobs=repository, settings=configured, access=service))

        @staticmethod
        async def is_disconnected() -> bool:
            return False

    async def collect_settled_stream() -> list[bytes]:
        return [
            chunk
            async for chunk in stream_job_events(
                ConnectedRequest(),  # type: ignore[arg-type]
                owner_session_id=owner,
                job_id=job.id,
                cursor=0,
                session_token=token,
            )
        ]

    settled_chunks = asyncio.run(collect_settled_stream())
    assert b'"state":"failed_retryable"' in settled_chunks[-1]
    repository.retry(owner, job.id)
    retried = repository.list_events(owner, job.id)[-1]
    assert retried.event_type == "retried"
    assert retried.error_code is None and retried.error_retryable is False and retried.can_retry is False


def test_sse_resume_ownership_and_restart(tmp_path: Path, monkeypatch) -> None:
    configured = replace(
        settings,
        database_path=tmp_path / "api-events.sqlite3",
        storage_root=tmp_path / "assets",
        access_code_enabled=True,
        sse_heartbeat_seconds=0.05,
        sse_poll_seconds=0.01,
    )
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as first_client:
        code, _ = first_client.app.state.access.issue_code("owner")
        exchange = first_client.post("/api/v1/access/exchange-code", json={"code": code})
        csrf = exchange.json()["csrf_token"]
        session_cookie = exchange.cookies[configured.cookie_name]
        owner = first_client.app.state.access.authenticate(session_cookie)["id"]
        page_id = _seed_page(first_client.app.state.database, owner)
        created = first_client.post(
            f"/api/v1/pages/{page_id}/recognition-jobs",
            json={},
            headers={"Idempotency-Key": "sse-api-job-key-0001", "X-CSRF-Token": csrf},
        )
        job_id = created.json()["id"]
        cancelled = first_client.post(f"/api/v1/jobs/{job_id}/cancel", headers={"X-CSRF-Token": csrf})
        assert cancelled.status_code == 200

    with TestClient(main_module.create_app()) as restarted_client:
        restarted_client.cookies.set(configured.cookie_name, session_cookie)
        response = restarted_client.get(
            f"/events/jobs/{job_id}?after=0",
            headers={"Last-Event-ID": "1"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert "id: 1\n" not in response.text
        assert "id: 2\n" in response.text
        assert '"event_type":"cancelled"' in response.text
        assert restarted_client.get(f"/events/jobs/{job_id}?after=2").text == ""
        assert restarted_client.get(
            f"/events/jobs/{job_id}", headers={"Last-Event-ID": "not-a-sequence"}
        ).status_code == 400
        assert restarted_client.get(f"/events/jobs/{job_id}?after=3").status_code == 409

        other_code, _ = restarted_client.app.state.access.issue_code("other")
        restarted_client.post("/api/v1/access/exchange-code", json={"code": other_code})
        assert restarted_client.get(f"/events/jobs/{job_id}").status_code == 404


def test_sse_heartbeat_then_disconnect_has_no_background_task(tmp_path: Path) -> None:
    database = Database(tmp_path / "heartbeat.sqlite3")
    database.migrate()
    configured = replace(
        settings,
        database_path=database.path,
        storage_root=tmp_path / "assets",
        sse_heartbeat_seconds=0.01,
        sse_poll_seconds=0.002,
    )
    service, owner, token = _access(database, configured, "owner")
    page_id = _seed_page(database, owner)
    repository = JobRepository(database)
    job, _ = repository.enqueue(
        owner,
        page_id,
        "heartbeat-job-key-001",
        priority=0,
        capacity=10,
        max_attempts=3,
    )

    class DisconnectingRequest:
        def __init__(self) -> None:
            self.app = SimpleNamespace(
                state=SimpleNamespace(jobs=repository, settings=configured, access=service)
            )
            self.checks = 0

        async def is_disconnected(self) -> bool:
            self.checks += 1
            return self.checks >= 20

    request = DisconnectingRequest()

    async def collect() -> tuple[list[bytes], int]:
        chunks: list[bytes] = []
        async for chunk in stream_job_events(
            request,  # type: ignore[arg-type]
            owner_session_id=owner,
            job_id=job.id,
            cursor=1,
            session_token=token,
        ):
            chunks.append(chunk)
        remaining_tasks = len([task for task in asyncio.all_tasks() if task is not asyncio.current_task()])
        return chunks, remaining_tasks

    chunks, remaining_tasks = asyncio.run(collect())
    assert b": heartbeat\n\n" in chunks
    assert request.checks >= 20
    assert remaining_tasks == 0


def test_expired_access_cannot_open_sse(tmp_path: Path, monkeypatch) -> None:
    configured = replace(
        settings,
        database_path=tmp_path / "expired.sqlite3",
        storage_root=tmp_path / "assets",
        access_code_enabled=True,
    )
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as client:
        code, _ = client.app.state.access.issue_code("owner")
        exchange = client.post("/api/v1/access/exchange-code", json={"code": code})
        token = exchange.cookies[configured.cookie_name]
        owner = client.app.state.access.authenticate(token)["id"]
        page_id = _seed_page(client.app.state.database, owner)
        job, _ = client.app.state.jobs.enqueue(
            owner,
            page_id,
            "expired-sse-job-0001",
            priority=0,
            capacity=10,
            max_attempts=3,
        )
        with client.app.state.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE access_sessions SET expires_at=? WHERE id=?",
                ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), owner),
            )
        response = client.get(f"/events/jobs/{job.id}")

    assert response.status_code == 401
    assert response.json()["code"] == "access_denied"
