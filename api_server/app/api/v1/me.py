from __future__ import annotations

from fastapi import APIRouter, Depends, Request

from app.api.dependencies import (
    AuthenticatedSession,
    require_mutation_session,
    require_session,
)
from app.core.errors import ApiError
from app.schemas.contracts import (
    AccountProfile,
    AccountSessionItem,
    AccountSessionList,
    ProfilePatch,
    RevokeSessionsResponse,
)

router = APIRouter(prefix="/me", tags=["account"])


def _require_account(session: AuthenticatedSession) -> str:
    if session.user_id is None or session.auth_method != "account":
        raise ApiError(403, "account_required", "Sign in with an account to use this endpoint.")
    return session.user_id


def _profile(value: dict) -> AccountProfile:
    return AccountProfile(
        id=value["id"],
        email=value["email"],
        name=value["name"],
        email_verified=value["email_verified_at"] is not None,
        created_at=value["created_at"],
        updated_at=value["updated_at"],
    )


@router.get("", response_model=AccountProfile)
def get_me(
    request: Request, session: AuthenticatedSession = Depends(require_session)
) -> AccountProfile:
    return _profile(request.app.state.access.get_profile(_require_account(session)))


@router.patch("", response_model=AccountProfile)
def patch_me(
    payload: ProfilePatch,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> AccountProfile:
    try:
        value = request.app.state.access.update_profile(_require_account(session), payload.name)
    except ValueError as error:
        raise ApiError(422, "invalid_name", "The profile name is invalid.") from error
    return _profile(value)


@router.get("/sessions", response_model=AccountSessionList)
def sessions(
    request: Request, session: AuthenticatedSession = Depends(require_session)
) -> AccountSessionList:
    items = request.app.state.access.list_sessions(
        _require_account(session), session.session_id
    )
    return AccountSessionList(items=[AccountSessionItem(**item) for item in items])


@router.delete("/sessions/{session_id}", response_model=RevokeSessionsResponse)
def revoke_session(
    session_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> RevokeSessionsResponse:
    changed = request.app.state.access.revoke_session(_require_account(session), session_id)
    if not changed:
        raise ApiError(404, "session_not_found", "The session was not found.")
    return RevokeSessionsResponse(revoked_count=1)


@router.post("/sessions/revoke-others", response_model=RevokeSessionsResponse)
def revoke_others(
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> RevokeSessionsResponse:
    count = request.app.state.access.revoke_other_sessions(
        _require_account(session), session.session_id
    )
    return RevokeSessionsResponse(revoked_count=count)
