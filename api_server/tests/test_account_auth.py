from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.database import Database
from app.core.settings import settings
from app.repositories.documents import DocumentRepository
from app.services.access import AccessDenied, AccessService, InvalidToken, RateLimited


@pytest.fixture
def account_runtime(tmp_path):
    configured = replace(
        settings,
        database_path=tmp_path / "accounts.sqlite3",
        storage_root=tmp_path / "assets",
        environment="development",
        access_code_enabled=True,
        account_attempt_limit=2,
        account_attempt_window_seconds=900,
    )
    database = Database(configured.database_path)
    database.migrate()
    return configured, database, AccessService(database, configured)


def create_verified_account(service: AccessService, email: str, password: str = "correct horse battery") -> str:
    registration = service.register(email, password, "Test User")
    service.verify_email(email, registration.verification_code)
    return registration.user_id


def test_argon2id_tokens_single_use_and_password_reset_revokes_sessions(account_runtime) -> None:
    _, database, service = account_runtime
    registration = service.register("owner@example.test", "correct horse battery", "Owner")
    with database.connect() as connection:
        user = connection.execute("SELECT password_hash FROM users WHERE id=?", (registration.user_id,)).fetchone()
        verification = connection.execute(
            "SELECT token_hash FROM email_verification_tokens WHERE user_id=?", (registration.user_id,)
        ).fetchone()
    assert user["password_hash"].startswith("$argon2id$")
    assert registration.verification_code.encode() not in bytes(verification["token_hash"])

    service.verify_email(registration.email, registration.verification_code)
    with pytest.raises(InvalidToken):
        service.verify_email(registration.email, registration.verification_code)

    grant = service.login(registration.email, "correct horse battery", "client", "Browser A")
    reset_code, _ = service.request_password_reset(registration.email)
    assert reset_code is not None
    service.confirm_password_reset(registration.email, reset_code, "a completely new password")
    with pytest.raises(AccessDenied):
        service.authenticate(grant.token)
    with pytest.raises(InvalidToken):
        service.confirm_password_reset(registration.email, reset_code, "another long password")
    service.login(registration.email, "a completely new password", "client", "Browser A")


def test_existing_database_is_backed_up_before_account_migration(tmp_path) -> None:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_base.sql").write_text(
        "CREATE TABLE preserved(value TEXT NOT NULL); INSERT INTO preserved VALUES ('before');",
        encoding="utf-8",
    )
    path = tmp_path / "existing.sqlite3"
    database = Database(path, migrations)
    database.migrate()
    (migrations / "002_accounts.sql").write_text(
        "CREATE TABLE users(id TEXT PRIMARY KEY);", encoding="utf-8"
    )
    database.migrate()
    backup_path = tmp_path / "existing.sqlite3.backup-before-002_accounts"
    assert backup_path.exists()
    with Database(backup_path, migrations).connect() as connection:
        assert connection.execute("SELECT value FROM preserved").fetchone()[0] == "before"
        assert connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
        ).fetchone() is None


def test_failed_login_attempts_are_persisted_and_limited(account_runtime) -> None:
    configured, database, service = account_runtime
    create_verified_account(service, "limited@example.test")
    for _ in range(configured.account_attempt_limit):
        with pytest.raises(AccessDenied):
            service.login("limited@example.test", "wrong", "attacker", "Browser")
    with pytest.raises(RateLimited):
        service.login("limited@example.test", "wrong", "attacker", "Browser")
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM account_attempts WHERE succeeded=0").fetchone()[0] == 2


def test_active_sessions_can_be_listed_and_revoked_without_cross_user_access(
    account_runtime,
) -> None:
    _, _, service = account_runtime
    first_user = create_verified_account(service, "sessions@example.test")
    first = service.login(
        "sessions@example.test", "correct horse battery", "one", "Browser One"
    )
    second = service.login(
        "sessions@example.test", "correct horse battery", "two", "Browser Two"
    )
    second_current = service.authenticate(second.token)
    sessions = service.list_sessions(first_user, second_current["id"])
    assert len(sessions) == 2
    assert {item["user_agent"] for item in sessions} == {"Browser One", "Browser Two"}
    assert sum(item["current"] for item in sessions) == 1

    other_user = create_verified_account(service, "other-sessions@example.test")
    assert service.revoke_session(other_user, first.session_id) is False
    assert service.revoke_other_sessions(first_user, second.session_id) == 1
    with pytest.raises(AccessDenied):
        service.authenticate(first.token)
    assert service.authenticate(second.token)["user_id"] == first_user


def test_legacy_documents_are_claimed_without_cross_account_access(account_runtime) -> None:
    _, database, service = account_runtime
    code, _ = service.issue_code()
    legacy = service.exchange(code, "legacy")
    repository = DocumentRepository(database)
    document = repository.create(legacy.session_id, "Legacy document")

    first = service.register(
        "first@example.test", "correct horse battery", "First", legacy.token
    )
    service.verify_email(first.email, first.verification_code)
    first_grant = service.login(first.email, "correct horse battery", "first", "Browser")
    first_session = service.authenticate(first_grant.token)
    assert repository.get(first_session["owner_id"], document.id).title == "Legacy document"
    with pytest.raises(AccessDenied):
        service.authenticate(legacy.token)

    create_verified_account(service, "second@example.test")
    second_grant = service.login(
        "second@example.test", "correct horse battery", "second", "Browser"
    )
    second_session = service.authenticate(second_grant.token)
    with pytest.raises(KeyError):
        repository.get(second_session["owner_id"], document.id)


def test_account_http_flow_profile_sessions_logout_and_generic_recovery(
    account_runtime, monkeypatch
) -> None:
    configured, _, _ = account_runtime
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as client:
        registered = client.post(
            "/api/v1/access/register",
            json={
                "email": "http@example.test",
                "name": "HTTP User",
                "password": "correct horse battery",
            },
        )
        assert registered.status_code == 201
        code = registered.json()["development_code"]
        assert client.post(
            "/api/v1/access/email/verify",
            json={"email": "http@example.test", "code": code},
        ).status_code == 200
        login = client.post(
            "/api/v1/access/login",
            json={"email": "http@example.test", "password": "correct horse battery"},
            headers={"User-Agent": "Test Browser"},
        )
        assert login.status_code == 200
        assert login.json()["auth_method"] == "account"
        assert "HttpOnly" in login.headers["set-cookie"]
        csrf = login.json()["csrf_token"]

        profile = client.get("/api/v1/me")
        assert profile.status_code == 200 and profile.json()["email"] == "http@example.test"
        patched = client.patch(
            "/api/v1/me", json={"name": "Updated User"}, headers={"X-CSRF-Token": csrf}
        )
        assert patched.status_code == 200 and patched.json()["name"] == "Updated User"
        sessions = client.get("/api/v1/me/sessions")
        assert sessions.status_code == 200
        assert sessions.json()["items"][0]["current"] is True

        known = client.post(
            "/api/v1/access/recovery/request", json={"email": "http@example.test"}
        )
        unknown = client.post(
            "/api/v1/access/recovery/request", json={"email": "unknown@example.test"}
        )
        assert known.status_code == unknown.status_code == 200
        assert known.json()["accepted"] is unknown.json()["accepted"] is True
        assert set(known.json()) == set(unknown.json())
        assert len(known.json()["development_code"]) == len(unknown.json()["development_code"]) == 6

        assert client.post(
            "/api/v1/access/logout", headers={"X-CSRF-Token": csrf}
        ).status_code == 204
        assert client.get("/api/v1/me").status_code == 401


def test_access_code_http_route_is_disabled_without_explicit_flag(
    account_runtime, monkeypatch
) -> None:
    configured, _, service = account_runtime
    disabled = replace(configured, access_code_enabled=False)
    code, _ = service.issue_code("admin")
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", disabled)
    with TestClient(main_module.create_app()) as client:
        response = client.post("/api/v1/access/exchange-code", json={"code": code})
    assert response.status_code == 404
    assert response.json()["code"] == "access_code_disabled"
