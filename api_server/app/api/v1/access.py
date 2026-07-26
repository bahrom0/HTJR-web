from __future__ import annotations

from fastapi import APIRouter, Cookie, Header, Request, Response

from app.core.errors import ApiError
from app.schemas.contracts import (
    AccessExchangeRequest,
    AccessSession,
    AccountLoginRequest,
    AccountProfile,
    AccountRegisterRequest,
    AccountRegistrationResponse,
    EmailCodeRequest,
    EmailOnlyRequest,
    GenericAcceptedResponse,
    PasswordResetConfirmRequest,
)
from app.services.access import (
    AccessCodeDisabled,
    AccessDenied,
    AccessService,
    AccountExists,
    InvalidToken,
    RateLimited,
    VerificationRequired,
)

router = APIRouter(prefix="/access", tags=["access"])
SESSION_COOKIE_PATH = "/"


def _service(request: Request) -> AccessService:
    return request.app.state.access


def _deny(message: str = "The access code or session is invalid.") -> ApiError:
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


def _profile(current: dict) -> AccountProfile | None:
    if current["auth_method"] != "account":
        return None
    return AccountProfile(
        id=current["user_id"],
        email=current["email"],
        name=current["name"],
        email_verified=current["email_verified_at"] is not None,
        created_at=current["created_at"],
        updated_at=current["updated_at"],
    )


@router.post("/exchange-code", response_model=AccessSession)
def exchange(payload: AccessExchangeRequest, request: Request, response: Response) -> AccessSession:
    if not request.app.state.settings.access_code_enabled:
        raise ApiError(404, "access_code_disabled", "Access-code sign in is disabled.")
    try:
        grant = _service(request).exchange(payload.code, _client_key(request))
    except AccessCodeDisabled as error:
        raise ApiError(404, "access_code_disabled", "Access-code sign in is disabled.") from error
    except RateLimited as error:
        raise ApiError(429, "rate_limited", "Too many access attempts. Try again later.", True) from error
    except AccessDenied as error:
        raise _deny("The access code or session is invalid.") from error
    _set_session_cookie(request, response, grant.token)
    return AccessSession(
        authenticated=True,
        expires_at=grant.expires_at,
        csrf_token=grant.csrf_token,
        auth_method="access_code",
    )


@router.post("/register", response_model=AccountRegistrationResponse, status_code=201)
def register(
    payload: AccountRegisterRequest, request: Request
) -> AccountRegistrationResponse:
    legacy_token = request.cookies.get(request.app.state.settings.cookie_name)
    try:
        registration = _service(request).register(
            payload.email, payload.password, payload.name, legacy_token
        )
    except AccountExists as error:
        raise ApiError(409, "account_exists", "An account with this email already exists.") from error
    except ValueError as error:
        raise ApiError(422, "invalid_account", "Check the name, email, and password requirements.") from error
    development_code = (
        registration.verification_code
        if request.app.state.settings.environment == "development"
        else None
    )
    return AccountRegistrationResponse(
        email=registration.email,
        verification_expires_at=registration.verification_expires_at,
        development_code=development_code,
    )


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
    except VerificationRequired as error:
        raise ApiError(403, "email_not_verified", "Confirm your email before signing in.") from error
    except AccessDenied as error:
        raise _deny("The email or password is incorrect.") from error
    _set_session_cookie(request, response, grant.token)
    current = _service(request).authenticate(grant.token)
    return AccessSession(
        authenticated=True,
        expires_at=grant.expires_at,
        csrf_token=grant.csrf_token,
        auth_method="account",
        user=_profile(current),
    )


@router.post("/email/verify", response_model=GenericAcceptedResponse)
def verify_email(payload: EmailCodeRequest, request: Request) -> GenericAcceptedResponse:
    try:
        _service(request).verify_email(payload.email, payload.code)
    except (InvalidToken, ValueError) as error:
        raise ApiError(400, "invalid_or_expired_code", "The confirmation code is invalid or expired.") from error
    return GenericAcceptedResponse()


@router.post("/email/resend", response_model=GenericAcceptedResponse)
def resend_email(payload: EmailOnlyRequest, request: Request) -> GenericAcceptedResponse:
    try:
        code, expires_at = _service(request).resend_verification(payload.email)
    except (RateLimited, ValueError) as error:
        if isinstance(error, RateLimited):
            raise ApiError(429, "rate_limited", "Wait before requesting another code.", True) from error
        code, expires_at = None, None
    return GenericAcceptedResponse(
        development_code=code if request.app.state.settings.environment == "development" else None,
        expires_at=expires_at,
    )


@router.post("/recovery/request", response_model=GenericAcceptedResponse)
def recovery_request(payload: EmailOnlyRequest, request: Request) -> GenericAcceptedResponse:
    code, expires_at = _service(request).request_password_reset(payload.email)
    # The public response is deliberately identical for known and unknown email
    # addresses. Development codes exist only for the local, non-production UI.
    return GenericAcceptedResponse(
        development_code=code if request.app.state.settings.environment == "development" else None,
        expires_at=expires_at if request.app.state.settings.environment == "development" else None,
    )


@router.post("/recovery/confirm", response_model=GenericAcceptedResponse)
def recovery_confirm(
    payload: PasswordResetConfirmRequest, request: Request
) -> GenericAcceptedResponse:
    try:
        _service(request).confirm_password_reset(
            payload.email, payload.code, payload.new_password
        )
    except (InvalidToken, ValueError) as error:
        raise ApiError(400, "invalid_or_expired_code", "The reset code is invalid or expired.") from error
    return GenericAcceptedResponse()


@router.get("/session", response_model=AccessSession)
def session(
    request: Request, htr_session: str | None = Cookie(default=None, alias="htr_session")
) -> AccessSession:
    token = request.cookies.get(request.app.state.settings.cookie_name, htr_session)
    try:
        current = _service(request).authenticate(token)
    except AccessDenied as error:
        raise _deny() from error
    return AccessSession(
        authenticated=True,
        expires_at=current["expires_at"],
        auth_method=current["auth_method"],
        user=_profile(current),
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
        auth_method=current["auth_method"],
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
