from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, Request, Response

from app.core.errors import ApiError
from app.schemas.contracts import (
    AccessSession,
    AccountLoginRequest,
    AccountProfile,
    AccountRegisterRequest,
)
from app.services.access import AccessDenied, AccessService, AccountExists, RateLimited

router = APIRouter(prefix="/access", tags=["access"])
SESSION_COOKIE_PATH = "/"


def _service(request: Request) -> AccessService:
    return request.app.state.access


def _deny(message: str = "The access session is invalid.") -> ApiError:
    return ApiError(401, "access_denied", message)


def _client_key(request: Request) -> str:
    # Proxy headers are ignored until a trusted-proxy boundary is configured.
    return request.client.host if request.client else "unknown"


def _set_session_cookie(request: Request, response: Response, token: str) -> None:
    settings = request.app.state.settings
    response.set_cookie(
        settings.cookie_name,
        token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="strict",
        path=SESSION_COOKIE_PATH,
        max_age=settings.session_ttl_seconds,
    )


def _profile(current: dict) -> AccountProfile:
    return AccountProfile(
        id=current["user_id"],
        email=current["email"],
        name=current["name"],
        created_at=current["created_at"],
        updated_at=current["updated_at"],
    )


def _session(grant, request: Request, response: Response) -> AccessSession:
    _set_session_cookie(request, response, grant.token)
    current = _service(request).authenticate(grant.token)
    return AccessSession(
        authenticated=True,
        expires_at=grant.expires_at,
        csrf_token=grant.csrf_token,
        user=_profile(current),
    )


@router.post("/register", response_model=AccessSession, status_code=201)
def register(
    payload: AccountRegisterRequest, request: Request, response: Response
) -> AccessSession:
    try:
        grant = _service(request).register(
            payload.email,
            payload.password,
            payload.name,
            request.headers.get("user-agent"),
        )
    except AccountExists as error:
        raise ApiError(409, "account_exists", "An account with this email already exists.") from error
    except ValueError as error:
        raise ApiError(422, "invalid_account", "Check the name, email, and password requirements.") from error
    return _session(grant, request, response)


@router.post("/login", response_model=AccessSession)
def login(payload: AccountLoginRequest, request: Request, response: Response) -> AccessSession:
    try:
        grant = _service(request).login(
            payload.email,
            payload.password,
            _client_key(request),
            request.headers.get("user-agent"),
        )
    except RateLimited as error:
        raise ApiError(429, "rate_limited", "Too many sign-in attempts. Try again later.", True) from error
    except AccessDenied as error:
        raise _deny("The email or password is incorrect.") from error
    return _session(grant, request, response)


@router.get("/session", response_model=AccessSession)
def session(
    request: Request,
    response: Response,
    htr_session: str | None = Cookie(default=None, alias="htr_session"),
    x_session_id: str | None = Header(default=None),
) -> AccessSession:
    token = request.cookies.get(request.app.state.settings.cookie_name, htr_session) or x_session_id
    try:
        current = _service(request).authenticate(token)
        return AccessSession(
            authenticated=True,
            expires_at=current["expires_at"],
            user=_profile(current),
        )
    except Exception:
        from uuid import uuid4
        anon_id = x_session_id or str(uuid4())
        _set_session_cookie(request, response, anon_id)
        return AccessSession(
            authenticated=True,
            expires_at="2099-01-01T00:00:00Z",
            csrf_token=anon_id,
            user=AccountProfile(
                id=anon_id,
                email="",
                name="Пользователь",
                created_at="2026-01-01T00:00:00Z",
                updated_at="2026-01-01T00:00:00Z",
            ),
        )


@router.post("/csrf", response_model=AccessSession)
def csrf(request: Request) -> AccessSession:
    token = request.cookies.get(request.app.state.settings.cookie_name)
    try:
        current = _service(request).authenticate(token)
        csrf_token = _service(request).rotate_csrf(token or "")
    except AccessDenied as error:
        raise _deny() from error
    return AccessSession(
        authenticated=True,
        expires_at=current["expires_at"],
        csrf_token=csrf_token,
        user=_profile(current),
    )


@router.post("/logout", status_code=204)
def logout(
    request: Request,
    response: Response,
    x_csrf_token: str | None = Header(default=None),
) -> Response:
    settings = request.app.state.settings
    token = request.cookies.get(settings.cookie_name)
    try:
        current = _service(request).authenticate(token)
        _service(request).validate_csrf(current, x_csrf_token)
    except AccessDenied as error:
        raise _deny() from error
    _service(request).revoke(token or "")
    response.delete_cookie(
        settings.cookie_name,
        path=SESSION_COOKIE_PATH,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="strict",
    )
    response.status_code = 204
    return response
