from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from app.api.dependencies import AuthenticatedSession, require_session, require_mutation_session
from app.schemas.contracts import AccountProfile, AccountSessionList, RevokeSessionsResponse

router = APIRouter(prefix="/me", tags=["account"])


@router.get("", response_model=AccountProfile)
def get_me(
    request: Request, session: AuthenticatedSession = Depends(require_session)
) -> AccountProfile:
    return AccountProfile(
        id=session.user_id,
        email="user@htr.local",
        name="Пользователь",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


@router.patch("", response_model=AccountProfile)
def patch_me(
    request: Request, session: AuthenticatedSession = Depends(require_mutation_session)
) -> AccountProfile:
    return AccountProfile(
        id=session.user_id,
        email="user@htr.local",
        name="Пользователь",
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
    )


@router.get("/sessions", response_model=AccountSessionList)
def sessions(
    request: Request, session: AuthenticatedSession = Depends(require_session)
) -> AccountSessionList:
    return AccountSessionList(items=[])


@router.delete("/sessions/{session_id}", response_model=RevokeSessionsResponse)
def revoke_session(session_id: str) -> RevokeSessionsResponse:
    return RevokeSessionsResponse(revoked_count=1)


@router.post("/sessions/revoke-others", response_model=RevokeSessionsResponse)
def revoke_others() -> RevokeSessionsResponse:
    return RevokeSessionsResponse(revoked_count=0)
