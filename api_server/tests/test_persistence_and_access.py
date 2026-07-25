from __future__ import annotations

import io
import sqlite3
from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.database import Database
from app.core.settings import settings
from app.core.storage import FileStorage
from app.repositories.documents import DocumentRepository, RevisionConflict
from app.services.access import AccessDenied, AccessService, RateLimited


@pytest.fixture
def configured(tmp_path):
    configured_settings = replace(
        settings,
        database_path=tmp_path / "studio.sqlite3",
        storage_root=tmp_path / "assets",
        access_attempt_limit=2,
        access_attempt_window_seconds=300,
    )
    database = Database(configured_settings.database_path)
    database.migrate()
    return configured_settings, database


def create_session(configured) -> tuple[AccessService, str, str]:
    configured_settings, database = configured
    service = AccessService(database, configured_settings)
    code, _ = service.issue_code("tests")
    grant = service.exchange(code, "127.0.0.1")
    return service, grant.session_id, grant.token


def test_migrations_are_idempotent_and_survive_restart(configured) -> None:
    configured_settings, database = configured
    service, session_id, _ = create_session(configured)
    document = DocumentRepository(database).create(session_id, "Манускрипт")
    Database(configured_settings.database_path).migrate()
    assert DocumentRepository(Database(configured_settings.database_path)).get(session_id, document.id).title == "Манускрипт"
    assert service.authenticate(_)["id"] == session_id


def test_transaction_rolls_back_and_foreign_keys_reject_orphan(configured) -> None:
    _, database = configured
    with pytest.raises(RuntimeError), database.transaction() as connection:
        connection.execute("INSERT INTO access_attempts(client_key,attempted_at) VALUES ('x','now')")
        raise RuntimeError("rollback")
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM access_attempts").fetchone()[0] == 0
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO assets(id,owner_session_id,storage_key,sha256,byte_size,media_type,state,created_at) VALUES ('a','missing','key','hash',1,'image/png','committed','now')"
            )


def test_revision_conflict_soft_delete_and_ownership(configured) -> None:
    _, database = configured
    _, owner, _ = create_session(configured)
    service = AccessService(database, configured[0])
    code, _ = service.issue_code()
    other = service.exchange(code, "other").session_id
    repository = DocumentRepository(database)
    document = repository.create(owner, "A")
    updated = repository.update(owner, document.id, 1, title="B")
    with pytest.raises(RevisionConflict):
        repository.update(owner, document.id, 1, title="stale")
    with pytest.raises(KeyError):
        repository.get(other, document.id)
    repository.soft_delete(owner, document.id, updated.revision)
    with pytest.raises(KeyError):
        repository.get(owner, document.id)


def test_storage_is_hashed_atomic_and_contained(tmp_path) -> None:
    storage = FileStorage(tmp_path / "assets")
    staged = storage.stage(io.BytesIO(b"tajik htr"))
    assert staged.sha256 == "0a3240a409ec143d2f72303d50fe9e9e8f69aa373935f7ac39f5c0137991fdcc"
    committed = storage.commit(staged)
    assert committed.path.read_bytes() == b"tajik htr"
    assert not staged.path.exists()
    with pytest.raises(ValueError):
        storage.resolve("../escape")


def test_cascade_removes_document_children(configured) -> None:
    _, database = configured
    _, owner, _ = create_session(configured)
    repository = DocumentRepository(database)
    document = repository.create(owner, "Cascade")
    with database.transaction(immediate=True) as connection:
        connection.execute("INSERT INTO pages(id,document_id,page_index,created_at,updated_at) VALUES ('page',?,0,'now','now')", (document.id,))
        connection.execute("DELETE FROM documents WHERE id=?", (document.id,))
        assert connection.execute("SELECT COUNT(*) FROM pages WHERE id='page'").fetchone()[0] == 0


def test_code_replay_expiry_revoke_csrf_and_rate_limit(configured) -> None:
    configured_settings, database = configured
    service = AccessService(database, configured_settings)
    code, _ = service.issue_code()
    grant = service.exchange(code, "client")
    with pytest.raises(AccessDenied):
        service.exchange(code, "another-client")
    session = service.authenticate(grant.token)
    with pytest.raises(AccessDenied):
        service.validate_csrf(session, "wrong")
    service.validate_csrf(session, grant.csrf_token)
    service.revoke(grant.token)
    with pytest.raises(AccessDenied):
        service.authenticate(grant.token)

    expired_code, _ = service.issue_code()
    with database.transaction(immediate=True) as connection:
        connection.execute("UPDATE access_codes SET expires_at=? WHERE consumed_at IS NULL", ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(),))
    with pytest.raises(AccessDenied):
        service.exchange(expired_code, "expired")

    for _ in range(configured_settings.access_attempt_limit):
        with pytest.raises(AccessDenied):
            service.exchange("BAD-CODE-0000", "attacker")
    with pytest.raises(RateLimited):
        service.exchange("BAD-CODE-0000", "attacker")


def test_access_http_cookie_csrf_logout_and_release_flags(configured, monkeypatch) -> None:
    configured_settings, database = configured
    release_settings = replace(configured_settings, cookie_secure=True)
    service = AccessService(database, release_settings)
    code, _ = service.issue_code()
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", release_settings)
    with TestClient(main_module.create_app()) as client:
        exchange = client.post("/api/v1/access/exchange-code", json={"code": code})
        assert exchange.status_code == 200
        cookie = exchange.headers["set-cookie"]
        assert "HttpOnly" in cookie and "Secure" in cookie and "SameSite=strict" in cookie
        assert "Path=/" in cookie and "Path=/api/v1" not in cookie
        csrf_token = exchange.json()["csrf_token"]
        client.cookies.set(release_settings.cookie_name, exchange.cookies[release_settings.cookie_name])
        failed = client.post("/api/v1/access/logout", headers={"X-CSRF-Token": "wrong"})
        assert failed.status_code == 401
        logout = client.post("/api/v1/access/logout", headers={"X-CSRF-Token": csrf_token})
        assert logout.status_code == 204
        deleted_cookie = logout.headers["set-cookie"]
        assert "Max-Age=0" in deleted_cookie
        assert "Path=/" in deleted_cookie and "Path=/api/v1" not in deleted_cookie
