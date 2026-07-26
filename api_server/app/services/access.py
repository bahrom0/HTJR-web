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


class AccessCodeDisabled(Exception):
    pass


class AccountExists(Exception):
    pass


class VerificationRequired(Exception):
    pass


class InvalidToken(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: str
    token: str
    csrf_token: str
    expires_at: str
    auth_method: str = "access_code"


@dataclass(frozen=True, slots=True)
class AccountRegistration:
    user_id: str
    email: str
    name: str
    verification_code: str
    verification_expires_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _derive(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


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
    _owned_tables = (
        "documents",
        "assets",
        "recognition_jobs",
        "corrections",
        "export_artifacts",
        "upload_idempotency",
        "preprocessing_runs",
        "craft_detector_outputs",
        "recognition_line_crops",
        "recognition_line_results",
        "page_raw_results",
    )

    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def issue_code(self, label: str | None = None) -> tuple[str, str]:
        code = "-".join((secrets.token_hex(2), secrets.token_hex(2), secrets.token_hex(2))).upper()
        salt = secrets.token_bytes(16)
        now = _now()
        expires = now + timedelta(seconds=self.settings.access_code_ttl_seconds)
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO access_codes(id,salt,code_hash,created_at,expires_at,label) VALUES (?,?,?,?,?,?)",
                (str(uuid4()), salt, _derive(code, salt), now.isoformat(), expires.isoformat(), label),
            )
        return code, expires.isoformat()

    def exchange(self, code: str, client_key: str) -> SessionGrant:
        now = _now()
        window_start = (now - timedelta(seconds=self.settings.access_attempt_window_seconds)).isoformat()
        safe_client_key = _safe_key(client_key)
        grant: SessionGrant | None = None
        with self.database.transaction(immediate=True) as connection:
            attempts = connection.execute(
                "SELECT COUNT(*) FROM access_attempts WHERE client_key=? AND attempted_at>=? AND succeeded=0",
                (safe_client_key, window_start),
            ).fetchone()[0]
            if attempts >= self.settings.access_attempt_limit:
                raise RateLimited()
            rows = connection.execute(
                "SELECT id,salt,code_hash FROM access_codes WHERE consumed_at IS NULL AND expires_at>?",
                (now.isoformat(),),
            ).fetchall()
            matched = next(
                (
                    row
                    for row in rows
                    if hmac.compare_digest(_derive(code.strip().upper(), row["salt"]), row["code_hash"])
                ),
                None,
            )
            connection.execute(
                "INSERT INTO access_attempts(client_key,attempted_at,succeeded) VALUES (?,?,?)",
                (safe_client_key, now.isoformat(), int(matched is not None)),
            )
            if matched is not None:
                consumed = connection.execute(
                    "UPDATE access_codes SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
                    (now.isoformat(), matched["id"]),
                )
                if consumed.rowcount == 1:
                    grant = self._create_legacy_session(connection, now)
        if grant is None:
            raise AccessDenied()
        return grant

    def register(
        self,
        email: str,
        password: str,
        name: str,
        legacy_token: str | None = None,
    ) -> AccountRegistration:
        normalized = normalize_email(email)
        clean_name = " ".join(name.split())
        if not 2 <= len(clean_name) <= 100 or not 12 <= len(password) <= 128:
            raise ValueError("invalid_account_fields")
        now = _now()
        user_id = str(uuid4())
        code = self._new_human_token()
        expires = now + timedelta(seconds=self.settings.email_verification_ttl_seconds)
        legacy_owner: str | None = None
        if legacy_token:
            try:
                legacy = self.authenticate(legacy_token)
                if legacy["auth_method"] == "access_code":
                    legacy_owner = legacy["owner_id"]
            except AccessDenied:
                legacy_owner = None
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
            self._insert_verification_token(connection, user_id, code, now, expires)
            if legacy_owner:
                self._claim_legacy_ownership(connection, legacy_owner, user_id)
            self._audit(connection, "account_registered", now, user_id=user_id)
        return AccountRegistration(user_id, normalized, clean_name, code, expires.isoformat())

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
                    "SELECT id,email,name,password_hash,email_verified_at,disabled_at FROM users WHERE email=?",
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
                elif user["email_verified_at"] is None:
                    outcome = "verification_required"
                    self._audit(
                        connection,
                        "login_unverified",
                        now,
                        user_id=user["id"],
                        client_key_hash=client_hash,
                    )
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
        if outcome == "verification_required":
            raise VerificationRequired()
        if grant is None:
            raise AccessDenied()
        return grant

    def verify_email(self, email: str, code: str) -> None:
        normalized = normalize_email(email)
        now = _now()
        with self.database.transaction(immediate=True) as connection:
            user = connection.execute("SELECT id FROM users WHERE email=?", (normalized,)).fetchone()
            if user is None or not self._consume_token(
                connection, "email_verification_tokens", user["id"], code, now
            ):
                raise InvalidToken()
            connection.execute(
                "UPDATE users SET email_verified_at=COALESCE(email_verified_at,?),updated_at=? WHERE id=?",
                (now.isoformat(), now.isoformat(), user["id"]),
            )
            self._audit(connection, "email_verified", now, user_id=user["id"])

    def resend_verification(self, email: str) -> tuple[str | None, str | None]:
        normalized = normalize_email(email)
        now = _now()
        with self.database.transaction(immediate=True) as connection:
            user = connection.execute(
                "SELECT id,email_verified_at FROM users WHERE email=?", (normalized,)
            ).fetchone()
            if user is None or user["email_verified_at"] is not None:
                return None, None
            recent = connection.execute(
                """
                SELECT created_at FROM email_verification_tokens
                WHERE user_id=? ORDER BY created_at DESC LIMIT 1
                """,
                (user["id"],),
            ).fetchone()
            if recent and datetime.fromisoformat(recent["created_at"]) > now - timedelta(seconds=60):
                raise RateLimited()
            connection.execute(
                "UPDATE email_verification_tokens SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL",
                (now.isoformat(), user["id"]),
            )
            code = self._new_human_token()
            expires = now + timedelta(seconds=self.settings.email_verification_ttl_seconds)
            self._insert_verification_token(connection, user["id"], code, now, expires)
            self._audit(connection, "verification_resent", now, user_id=user["id"])
            return code, expires.isoformat()

    def request_password_reset(self, email: str) -> tuple[str | None, str | None]:
        now = _now()
        dummy_code = self._new_human_token()
        dummy_expires = (
            now + timedelta(seconds=self.settings.password_reset_ttl_seconds)
        ).isoformat()
        try:
            normalized = normalize_email(email)
        except ValueError:
            return dummy_code, dummy_expires
        with self.database.transaction(immediate=True) as connection:
            user = connection.execute(
                "SELECT id FROM users WHERE email=? AND disabled_at IS NULL", (normalized,)
            ).fetchone()
            if user is None:
                return dummy_code, dummy_expires
            connection.execute(
                "UPDATE password_reset_tokens SET consumed_at=? WHERE user_id=? AND consumed_at IS NULL",
                (now.isoformat(), user["id"]),
            )
            code = self._new_human_token()
            expires = now + timedelta(seconds=self.settings.password_reset_ttl_seconds)
            connection.execute(
                """
                INSERT INTO password_reset_tokens(id,user_id,token_hash,created_at,expires_at)
                VALUES (?,?,?,?,?)
                """,
                (str(uuid4()), user["id"], _token_hash(code), now.isoformat(), expires.isoformat()),
            )
            self._audit(connection, "password_reset_requested", now, user_id=user["id"])
            return code, expires.isoformat()

    def confirm_password_reset(self, email: str, code: str, new_password: str) -> None:
        if not 12 <= len(new_password) <= 128:
            raise ValueError("invalid_password")
        normalized = normalize_email(email)
        now = _now()
        with self.database.transaction(immediate=True) as connection:
            user = connection.execute("SELECT id FROM users WHERE email=?", (normalized,)).fetchone()
            if user is None or not self._consume_token(
                connection, "password_reset_tokens", user["id"], code, now
            ):
                raise InvalidToken()
            connection.execute(
                "UPDATE users SET password_hash=?,updated_at=? WHERE id=?",
                (self._password_hasher.hash(new_password), now.isoformat(), user["id"]),
            )
            connection.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL",
                (now.isoformat(), user["id"]),
            )
            self._audit(connection, "password_reset_confirmed", now, user_id=user["id"])

    def authenticate(self, token: str | None) -> dict:
        if not token:
            raise AccessDenied()
        now = _now().isoformat()
        with self.database.connect() as connection:
            row = connection.execute(
                """
                SELECT s.id,s.user_id,s.expires_at,s.csrf_hash,u.email,u.name,
                       u.email_verified_at,u.created_at,u.updated_at
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
                    "email_verified_at": row["email_verified_at"],
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "auth_method": "account",
                }
            legacy = connection.execute(
                """
                SELECT id,expires_at,csrf_hash FROM access_sessions
                WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?
                """,
                (_token_hash(token), now),
            ).fetchone()
            if legacy is None:
                raise AccessDenied()
            return {
                **dict(legacy),
                "owner_id": legacy["id"],
                "user_id": None,
                "email": None,
                "name": None,
                "auth_method": "access_code",
            }

    def validate_csrf(self, session: dict, csrf_token: str | None) -> None:
        if not csrf_token or not hmac.compare_digest(_token_hash(csrf_token), session["csrf_hash"]):
            raise AccessDenied()

    def revoke(self, token: str) -> None:
        now = _now().isoformat()
        token_digest = _token_hash(token)
        with self.database.transaction(immediate=True) as connection:
            changed = connection.execute(
                "UPDATE user_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (now, token_digest),
            )
            if changed.rowcount == 0:
                connection.execute(
                    "UPDATE access_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                    (now, token_digest),
                )

    def rotate_csrf(self, token: str) -> str:
        current = self.authenticate(token)
        csrf_token = secrets.token_urlsafe(32)
        table = "user_sessions" if current["auth_method"] == "account" else "access_sessions"
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                f"UPDATE {table} SET csrf_hash=? WHERE id=?",
                (_token_hash(csrf_token), current["id"]),
            )
        return csrf_token

    def get_profile(self, user_id: str) -> dict:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id,email,name,email_verified_at,created_at,updated_at FROM users WHERE id=?",
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

    def _create_legacy_session(self, connection, now: datetime) -> SessionGrant:
        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        session_id = str(uuid4())
        expires = now + timedelta(seconds=self.settings.session_ttl_seconds)
        connection.execute(
            """
            INSERT INTO access_sessions(id,token_hash,csrf_hash,created_at,expires_at,last_seen_at)
            VALUES (?,?,?,?,?,?)
            """,
            (
                session_id,
                _token_hash(token),
                _token_hash(csrf_token),
                now.isoformat(),
                expires.isoformat(),
                now.isoformat(),
            ),
        )
        return SessionGrant(session_id, token, csrf_token, expires.isoformat())

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
        return SessionGrant(session_id, token, csrf_token, expires.isoformat(), "account")

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

    def _claim_legacy_ownership(self, connection, legacy_owner: str, user_id: str) -> None:
        for table in self._owned_tables:
            connection.execute(
                f"UPDATE {table} SET owner_session_id=? WHERE owner_session_id=?",
                (user_id, legacy_owner),
            )
        connection.execute(
            """
            UPDATE text_versions SET created_by_session_id=?
            WHERE created_by_session_id=?
            """,
            (user_id, legacy_owner),
        )
        connection.execute(
            "UPDATE access_sessions SET revoked_at=? WHERE id=? AND revoked_at IS NULL",
            (_now().isoformat(), legacy_owner),
        )

    def _insert_verification_token(
        self, connection, user_id: str, code: str, now: datetime, expires: datetime
    ) -> None:
        connection.execute(
            """
            INSERT INTO email_verification_tokens(id,user_id,token_hash,created_at,expires_at)
            VALUES (?,?,?,?,?)
            """,
            (str(uuid4()), user_id, _token_hash(code), now.isoformat(), expires.isoformat()),
        )

    @staticmethod
    def _new_human_token() -> str:
        return f"{secrets.randbelow(1_000_000):06d}"

    @staticmethod
    def _consume_token(connection, table: str, user_id: str, code: str, now: datetime) -> bool:
        row = connection.execute(
            f"""
            SELECT id FROM {table}
            WHERE user_id=? AND token_hash=? AND consumed_at IS NULL AND expires_at>?
            ORDER BY created_at DESC LIMIT 1
            """,
            (user_id, _token_hash(code.strip()), now.isoformat()),
        ).fetchone()
        if row is None:
            return False
        result = connection.execute(
            f"UPDATE {table} SET consumed_at=? WHERE id=? AND consumed_at IS NULL",
            (now.isoformat(), row["id"]),
        )
        return result.rowcount == 1

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
