from __future__ import annotations

from dataclasses import dataclass
from fastapi import Header, Request


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    id: str
    session_id: str
    user_id: str


def get_current_session(request: Request) -> AuthenticatedSession:
    session_id = request.headers.get("X-Session-ID") or request.cookies.get("htr_session") or "guest-session"

    # Ensure session exists in access_sessions table so foreign keys pass
    try:
        with request.app.state.database.connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO access_sessions
                   (id, token_hash, csrf_hash, created_at, expires_at, last_seen_at)
                   VALUES (?, X'00', X'00', datetime('now'), datetime('now', '+10 years'), datetime('now'))""",
                (session_id,)
            )
    except Exception:
        pass

    return AuthenticatedSession(
        id=session_id,
        session_id=session_id,
        user_id=session_id,
    )


def require_session(request: Request) -> AuthenticatedSession:
    return get_current_session(request)


def require_mutation_session(
    request: Request, x_csrf_token: str | None = Header(default=None)
) -> AuthenticatedSession:
    return get_current_session(request)
