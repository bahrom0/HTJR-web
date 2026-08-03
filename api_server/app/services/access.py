from __future__ import annotations

import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type

from app.core.database import Database
from app.core.settings import Settings


class AccessDenied(Exception):
    pass


class RateLimited(Exception):
    pass


class AccountExists(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: str
    token: str
    csrf_token: str
    expires_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def _safe_key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def normalize_email(value: str) -> str:
    email = value.strip().casefold()
    if len(email) > 254 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email):
        raise ValueError("invalid_email")
    return email


class AccessService:
    _password_hasher = PasswordHasher(
        time_cost=3,
        memory_cost=65536,
        parallelism=2,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def register(
        self,
        email: str,
        password: str,
        name: str,
        user_agent: str | None,
    ) -> SessionGrant:
        normalized = normalize_email(email)
        clean_name = " ".join(name.split())
        if not 2 <= len(clean_name) <= 100 or not 12 <= len(password) <= 128:
            raise ValueError("invalid_account_fields")
        now = _now()
        user_id = str(uuid4())
        grant: SessionGrant
        with self.database.transaction(immediate=True) as connection:
            if connection.execute("SELECT 1 FROM users WHERE email=?", (normalized,)).fetchone():
                raise AccountExists()
            connection.execute(
                "INSERT INTO users(id,email,name,password_hash,created_at,updated_at) VALUES (?,?,?,?,?,?)",
                (
                    user_id,
                    normalized,
                    clean_name,
                    self._password_hasher.hash(password),
                    now.isoformat(),
                    now.isoformat(),
                ),
            )
            self._create_owner_anchor(connection, user_id, now)
            grant = self._create_user_session(connection, user_id, now, user_agent)
            self._audit(
                connection,
                "account_registered",
                now,
                user_id=user_id,
                session_id=grant.session_id,
            )
        return grant

    def login(self, email: str, password: str, client_key: str, user_agent: str | None) -> SessionGrant:
        try:
            normalized = normalize_email(email)
        except ValueError:
            normalized = email.strip().casefold()[:254]
        now = _now()
        client_hash = _safe_key(client_key)
        account_hash = _safe_key(normalized)
        window_start = (now - timedelta(seconds=self.settings.account_attempt_window_seconds)).isoformat()
        outcome = "denied"
        grant: SessionGrant | None = None
        with self.database.transaction(immediate=True) as connection:
            attempts = connection.execute(
                """
                SELECT COUNT(*) FROM account_attempts
                WHERE client_key_hash=? AND account_key_hash=? AND attempted_at>=? AND succeeded=0
                """,
                (client_hash, account_hash, window_start),
            ).fetchone()[0]
            if attempts >= self.settings.account_attempt_limit:
                self._audit(connection, "login_rate_limited", now, client_key_hash=client_hash)
                outcome = "rate_limited"
            else:
                user = connection.execute(
                    "SELECT id,email,name,password_hash,disabled_at FROM users WHERE email=?",
                    (normalized,),
                ).fetchone()
                valid = False
                if user is not None and user["disabled_at"] is None:
                    try:
                        valid = self._password_hasher.verify(user["password_hash"], password)
                    except (VerifyMismatchError, InvalidHashError):
                        valid = False
                connection.execute(
                    """
                    INSERT INTO account_attempts(client_key_hash,account_key_hash,attempted_at,succeeded)
                    VALUES (?,?,?,?)
                    """,
                    (client_hash, account_hash, now.isoformat(), int(valid)),
                )
                if not valid or user is None:
                    self._audit(connection, "login_failed", now, client_key_hash=client_hash)
                else:
                    outcome = "ok"
                    if self._password_hasher.check_needs_rehash(user["password_hash"]):
                        connection.execute(
                            "UPDATE users SET password_hash=?,updated_at=? WHERE id=?",
                            (self._password_hasher.hash(password), now.isoformat(), user["id"]),
                        )
                    grant = self._create_user_session(connection, user["id"], now, user_agent)
                    self._audit(
                        connection,
                        "login_succeeded",
                        now,
                        user_id=user["id"],
                        session_id=grant.session_id,
                        client_key_hash=client_hash,
                    )
        if outcome == "rate_limited":
            raise RateLimited()
        if grant is None:
            raise AccessDenied()
        return grant

    def authenticate(self, token: str | None) -> dict:
        if not token:
            raise AccessDenied()
        now = _now().isoformat()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT s.id,s.user_id,s.expires_at,s.csrf_hash,u.email,u.name,
                       u.created_at,u.updated_at
                FROM user_sessions s JOIN users u ON u.id=s.user_id
                WHERE s.token_hash=? AND s.revoked_at IS NULL AND s.expires_at>?
                  AND u.disabled_at IS NULL
                """,
                (_token_hash(token), now),
            ).fetchone()
            if row is not None:
                return {
                    "id": row["id"],
                    "owner_id": row["user_id"],
                    "user_id": row["user_id"],
                    "expires_at": row["expires_at"],
                    "csrf_hash": row["csrf_hash"],
                    "email": row["email"],
                    "name": row["name"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                }
        raise AccessDenied()

    def validate_csrf(self, session: dict, csrf_token: str | None) -> None:
        if not csrf_token or not hmac.compare_digest(_token_hash(csrf_token), session["csrf_hash"]):
            raise AccessDenied()

    def revoke(self, token: str) -> None:
        now = _now().isoformat()
        token_digest = _token_hash(token)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (now, token_digest),
            )

    def rotate_csrf(self, token: str) -> str:
        current = self.authenticate(token)
        csrf_token = secrets.token_urlsafe(32)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE user_sessions SET csrf_hash=? WHERE id=?",
                (_token_hash(csrf_token), current["id"]),
            )
        return csrf_token

    def get_profile(self, user_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id,email,name,created_at,updated_at FROM users WHERE id=?",
                (user_id,),
            ).fetchone()
            if row is None:
                raise AccessDenied()
            return dict(row)

    def update_profile(self, user_id: str, name: str) -> dict:
        clean_name = " ".join(name.split())
        if not 2 <= len(clean_name) <= 100:
            raise ValueError("invalid_name")
        now = _now().isoformat()
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE users SET name=?,updated_at=? WHERE id=?", (clean_name, now, user_id)
            )
        return self.get_profile(user_id)

    def list_sessions(self, user_id: str, current_session_id: str) -> list[dict]:
        now = _now().isoformat()
        with self.database.connect() as connection:
            rows = connection.execute(
                """
                SELECT id,created_at,expires_at,last_seen_at,user_agent
                FROM user_sessions
                WHERE user_id=? AND revoked_at IS NULL AND expires_at>?
                ORDER BY created_at DESC
                """,
                (user_id, now),
            ).fetchall()
            return [{**dict(row), "current": row["id"] == current_session_id} for row in rows]

    def revoke_session(self, user_id: str, session_id: str) -> bool:
        with self.database.transaction(immediate=True) as connection:
            result = connection.execute(
                """
                UPDATE user_sessions SET revoked_at=?
                WHERE id=? AND user_id=? AND revoked_at IS NULL
                """,
                (_now().isoformat(), session_id, user_id),
            )
            return result.rowcount == 1

    def revoke_other_sessions(self, user_id: str, current_session_id: str) -> int:
        with self.database.transaction(immediate=True) as connection:
            result = connection.execute(
                """
                UPDATE user_sessions SET revoked_at=?
                WHERE user_id=? AND id<>? AND revoked_at IS NULL
                """,
                (_now().isoformat(), user_id, current_session_id),
            )
            return result.rowcount

    def _create_user_session(
        self, connection, user_id: str, now: datetime, user_agent: str | None
    ) -> SessionGrant:
        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        session_id = str(uuid4())
        expires = now + timedelta(seconds=self.settings.session_ttl_seconds)
        safe_user_agent = (user_agent or "Unknown browser").strip()[:240]
        connection.execute(
            """
            INSERT INTO user_sessions(
              id,user_id,token_hash,csrf_hash,created_at,expires_at,last_seen_at,user_agent
            ) VALUES (?,?,?,?,?,?,?,?)
            """,
            (
                session_id,
                user_id,
                _token_hash(token),
                _token_hash(csrf_token),
                now.isoformat(),
                expires.isoformat(),
                now.isoformat(),
                safe_user_agent,
            ),
        )
        return SessionGrant(session_id, token, csrf_token, expires.isoformat())

    def _create_owner_anchor(self, connection, user_id: str, now: datetime) -> None:
        connection.execute(
            """
            INSERT INTO access_sessions(
              id,token_hash,csrf_hash,created_at,expires_at,revoked_at,last_seen_at
            ) VALUES (?,?,?,?,?,?,?)
            """,
            (
                user_id,
                secrets.token_bytes(32),
                secrets.token_bytes(32),
                now.isoformat(),
                (now + timedelta(days=36500)).isoformat(),
                now.isoformat(),
                now.isoformat(),
            ),
        )
        connection.execute(
            """
            INSERT INTO account_ownership_anchors(user_id,access_session_id,created_at)
            VALUES (?,?,?)
            """,
            (user_id, user_id, now.isoformat()),
        )

    @staticmethod
    def _audit(
        connection,
        event_type: str,
        now: datetime,
        *,
        user_id: str | None = None,
        session_id: str | None = None,
        client_key_hash: str | None = None,
    ) -> None:
        connection.execute(
            """
            INSERT INTO auth_security_events(
              event_type,user_id,session_id,client_key_hash,occurred_at
            ) VALUES (?,?,?,?,?)
            """,
            (event_type, user_id, session_id, client_key_hash, now.isoformat()),
        )
