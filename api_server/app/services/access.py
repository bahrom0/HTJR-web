from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.core.database import Database
from app.core.settings import Settings


class AccessDenied(Exception):
    pass


class RateLimited(Exception):
    pass


@dataclass(frozen=True, slots=True)
class SessionGrant:
    session_id: str
    token: str
    csrf_token: str
    expires_at: str


def _now() -> datetime:
    return datetime.now(UTC)


def _derive(secret: str, salt: bytes) -> bytes:
    return hashlib.scrypt(secret.encode("utf-8"), salt=salt, n=2**14, r=8, p=1, dklen=32)


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


class AccessService:
    def __init__(self, database: Database, settings: Settings) -> None:
        self.database = database
        self.settings = settings

    def issue_code(self, label: str | None = None) -> tuple[str, str]:
        code = "-".join((secrets.token_hex(2), secrets.token_hex(2), secrets.token_hex(2))).upper()
        salt = secrets.token_bytes(16)
        now = _now()
        expires = now + timedelta(seconds=self.settings.access_code_ttl_seconds)
        code_id = str(uuid4())
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO access_codes(id,salt,code_hash,created_at,expires_at,label) VALUES (?,?,?,?,?,?)",
                (code_id, salt, _derive(code, salt), now.isoformat(), expires.isoformat(), label),
            )
        return code, expires.isoformat()

    def exchange(self, code: str, client_key: str) -> SessionGrant:
        now = _now()
        window_start = (now - timedelta(seconds=self.settings.access_attempt_window_seconds)).isoformat()
        safe_client_key = hashlib.sha256(client_key.encode("utf-8")).hexdigest()
        grant: SessionGrant | None = None
        with self.database.transaction(immediate=True) as connection:
            attempts = connection.execute(
                "SELECT COUNT(*) FROM access_attempts WHERE client_key=? AND attempted_at>=? AND succeeded=0",
                (safe_client_key, window_start),
            ).fetchone()[0]
            if attempts >= self.settings.access_attempt_limit:
                raise RateLimited()
            rows = connection.execute(
                "SELECT id,salt,code_hash,expires_at FROM access_codes WHERE consumed_at IS NULL AND expires_at>?",
                (now.isoformat(),),
            ).fetchall()
            matched = next((row for row in rows if hmac.compare_digest(_derive(code.strip().upper(), row["salt"]), row["code_hash"])), None)
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
                    grant = self._create_session(connection, now)
        if grant is None:
            raise AccessDenied()
        return grant

    def _create_session(self, connection, now: datetime) -> SessionGrant:
        token = secrets.token_urlsafe(48)
        csrf_token = secrets.token_urlsafe(32)
        session_id = str(uuid4())
        expires = now + timedelta(seconds=self.settings.session_ttl_seconds)
        connection.execute(
            "INSERT INTO access_sessions(id,token_hash,csrf_hash,created_at,expires_at,last_seen_at) VALUES (?,?,?,?,?,?)",
            (session_id, _token_hash(token), _token_hash(csrf_token), now.isoformat(), expires.isoformat(), now.isoformat()),
        )
        return SessionGrant(session_id, token, csrf_token, expires.isoformat())

    def authenticate(self, token: str | None) -> dict:
        if not token:
            raise AccessDenied()
        now = _now().isoformat()
        # Authentication is on the hot path for every parallel UI request
        # (regions, preparation, job polling, previews and SSE).  It only
        # needs to validate the unexpired HttpOnly token.  Updating
        # ``last_seen_at`` here turned every read into a SQLite write and made
        # concurrent worker heartbeats surface as HTTP 500 ``database is
        # locked`` errors.  Session expiry is authoritative in ``expires_at``;
        # keep this path read-only so it cannot contend with ML job writes.
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id,expires_at,csrf_hash FROM access_sessions WHERE token_hash=? AND revoked_at IS NULL AND expires_at>?",
                (_token_hash(token), now),
            ).fetchone()
            if row is None:
                raise AccessDenied()
            return dict(row)

    def validate_csrf(self, session: dict, csrf_token: str | None) -> None:
        if not csrf_token or not hmac.compare_digest(_token_hash(csrf_token), session["csrf_hash"]):
            raise AccessDenied()

    def revoke(self, token: str) -> None:
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "UPDATE access_sessions SET revoked_at=? WHERE token_hash=? AND revoked_at IS NULL",
                (_now().isoformat(), _token_hash(token)),
            )

    def rotate_csrf(self, token: str) -> str:
        current = self.authenticate(token)
        csrf_token = secrets.token_urlsafe(32)
        with self.database.transaction(immediate=True) as connection:
            connection.execute("UPDATE access_sessions SET csrf_hash=? WHERE id=?", (_token_hash(csrf_token), current["id"]))
        return csrf_token
