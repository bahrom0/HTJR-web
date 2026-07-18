from __future__ import annotations

from dataclasses import dataclass

from fastapi import Header, Request

from app.core.errors import ApiError
from app.services.access import AccessDenied


@dataclass(frozen=True, slots=True)
class AuthenticatedSession:
    id: str


def require_session(request: Request) -> AuthenticatedSession:
    token = request.cookies.get(request.app.state.settings.cookie_name)
    try:
        current = request.app.state.access.authenticate(token)
    except AccessDenied as error:
        raise ApiError(401, "access_denied", "The access session is invalid or expired.") from error
    return AuthenticatedSession(id=current["id"])


def require_mutation_session(
    request: Request, x_csrf_token: str | None = Header(default=None)
) -> AuthenticatedSession:
    token = request.cookies.get(request.app.state.settings.cookie_name)
    try:
        current = request.app.state.access.authenticate(token)
        request.app.state.access.validate_csrf(current, x_csrf_token)
    except AccessDenied as error:
        raise ApiError(401, "access_denied", "The access session or CSRF token is invalid.") from error
    return AuthenticatedSession(id=current["id"])
