from __future__ import annotations

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.core.database import Database
from app.core.settings import settings
from app.services.access import AccessDenied, AccessService, RateLimited


@pytest.fixture
def account_runtime(tmp_path):
    configured = replace(
        settings,
        database_path=tmp_path / "accounts.sqlite3",
        storage_root=tmp_path / "assets",
        environment="development",
        account_attempt_limit=2,
        account_attempt_window_seconds=900,
    )
    database = Database(configured.database_path)
    database.migrate()
    return configured, database, AccessService(database, configured)


def create_account(
    service: AccessService, email: str, password: str = "correct horse battery"
) -> tuple[str, str]:
    grant = service.register(email, password, "Test User", "Test browser")
    return service.authenticate(grant.token)["user_id"], grant.token


def test_registration_creates_authenticated_argon2id_session_without_codes(account_runtime) -> None:
    _, database, service = account_runtime
    grant = service.register("owner@example.test", "correct horse battery", "Owner", "Browser")
    current = service.authenticate(grant.token)
    with database.connect() as connection:
        user = connection.execute("SELECT password_hash FROM users WHERE id=?", (current["user_id"],)).fetchone()
        tables = {
            row[0]
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        columns = {row[1] for row in connection.execute("PRAGMA table_info(users)").fetchall()}
    assert user["password_hash"].startswith("$argon2id$")
    assert {"access_codes", "email_verification_tokens", "password_reset_tokens"}.isdisjoint(tables)
    assert "email_verified_at" not in columns


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
    create_account(service, "limited@example.test")
    for _ in range(configured.account_attempt_limit):
        with pytest.raises(AccessDenied):
            service.login("limited@example.test", "wrong", "attacker", "Browser")
    with pytest.raises(RateLimited):
        service.login("limited@example.test", "wrong", "attacker", "Browser")
    with database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM account_attempts WHERE succeeded=0").fetchone()[0] == 2


def test_active_sessions_can_be_listed_and_revoked_without_cross_user_access(account_runtime) -> None:
    _, _, service = account_runtime
    first_user, registration_token = create_account(service, "sessions@example.test")
    first = service.login("sessions@example.test", "correct horse battery", "one", "Browser One")
    second = service.login("sessions@example.test", "correct horse battery", "two", "Browser Two")
    second_current = service.authenticate(second.token)
    sessions = service.list_sessions(first_user, second_current["id"])
    assert len(sessions) == 3
    assert {item["user_agent"] for item in sessions} == {"Test browser", "Browser One", "Browser Two"}
    assert sum(item["current"] for item in sessions) == 1

    other_user, _ = create_account(service, "other-sessions@example.test")
    assert service.revoke_session(other_user, first.session_id) is False
    assert service.revoke_other_sessions(first_user, second.session_id) == 2
    with pytest.raises(AccessDenied):
        service.authenticate(first.token)
    with pytest.raises(AccessDenied):
        service.authenticate(registration_token)
    assert service.authenticate(second.token)["user_id"] == first_user


def test_account_http_flow_profile_sessions_and_logout(account_runtime, monkeypatch) -> None:
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
            headers={"User-Agent": "Test Browser"},
        )
        assert registered.status_code == 201
        assert registered.json()["user"]["email"] == "http@example.test"
        assert "HttpOnly" in registered.headers["set-cookie"]
        csrf = registered.json()["csrf_token"]

        profile = client.get("/api/v1/me")
        assert profile.status_code == 200 and profile.json()["email"] == "http@example.test"
        patched = client.patch(
            "/api/v1/me", json={"name": "Updated User"}, headers={"X-CSRF-Token": csrf}
        )
        assert patched.status_code == 200 and patched.json()["name"] == "Updated User"
        sessions = client.get("/api/v1/me/sessions")
        assert sessions.status_code == 200
        assert sessions.json()["items"][0]["current"] is True

        assert client.post(
            "/api/v1/access/logout", headers={"X-CSRF-Token": csrf}
        ).status_code == 204
        assert client.get("/api/v1/me").status_code == 401


def test_code_routes_are_not_exposed(account_runtime, monkeypatch) -> None:
    configured, _, _ = account_runtime
    import app.main as main_module

    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as client:
        response = client.post("/api/v1/access/exchange-code", json={"code": "AAAA-BBBB-CCCC"})
        verification = client.post("/api/v1/access/email/verify", json={"email": "a@b.cd", "code": "123456"})
    assert response.status_code == verification.status_code == 404
