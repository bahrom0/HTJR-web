from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.core.errors import ApiError
from app.services.access import AccessDenied, AccessService, RateLimited

router = APIRouter(prefix="/access", tags=["access"])


class ExchangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str = Field(min_length=8, max_length=64)


class SessionResponse(BaseModel):
    authenticated: bool
    expires_at: str
    csrf_token: str | None = None


def _service(request: Request) -> AccessService:
    return request.app.state.access


def _deny() -> ApiError:
    return ApiError(401, "access_denied", "The access code or session is invalid.")


@router.post("/exchange", response_model=SessionResponse)
def exchange(payload: ExchangeRequest, request: Request, response: Response) -> SessionResponse:
    # Proxy headers are ignored until a trusted-proxy boundary is configured.
    client_key = request.client.host if request.client else "unknown"
    try:
        grant = _service(request).exchange(payload.code, client_key)
    except RateLimited as error:
        raise ApiError(429, "rate_limited", "Too many access attempts. Try again later.", True) from error
    except AccessDenied as error:
        raise _deny() from error
    settings = request.app.state.settings
    response.set_cookie(
        settings.cookie_name, grant.token, httponly=True, secure=settings.cookie_secure,
        samesite="strict", path="/api/v1", max_age=settings.session_ttl_seconds,
    )
    return SessionResponse(authenticated=True, expires_at=grant.expires_at, csrf_token=grant.csrf_token)


@router.get("/session", response_model=SessionResponse)
def session(request: Request, htr_session: str | None = Cookie(default=None, alias="htr_session")) -> SessionResponse:
    token = request.cookies.get(request.app.state.settings.cookie_name, htr_session)
    try:
        current = _service(request).authenticate(token)
    except AccessDenied as error:
        raise _deny() from error
    return SessionResponse(authenticated=True, expires_at=current["expires_at"])


@router.post("/csrf", response_model=SessionResponse)
def csrf(request: Request) -> SessionResponse:
    token = request.cookies.get(request.app.state.settings.cookie_name)
    try:
        current = _service(request).authenticate(token)
        csrf_token = _service(request).rotate_csrf(token or "")
    except AccessDenied as error:
        raise _deny() from error
    return SessionResponse(authenticated=True, expires_at=current["expires_at"], csrf_token=csrf_token)


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response, x_csrf_token: str | None = Header(default=None)) -> Response:
    settings = request.app.state.settings
    token = request.cookies.get(settings.cookie_name)
    try:
        current = _service(request).authenticate(token)
        _service(request).validate_csrf(current, x_csrf_token)
    except AccessDenied as error:
        raise _deny() from error
    _service(request).revoke(token or "")
    response.delete_cookie(settings.cookie_name, path="/api/v1", secure=settings.cookie_secure, httponly=True, samesite="strict")
    response.status_code = 204
    return response
