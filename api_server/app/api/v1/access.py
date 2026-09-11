from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/access", tags=["access"])


class UserProfile(BaseModel):
    id: str = "anonymous"
    email: str = "user@htr.local"
    name: str = "User"


class SessionResponse(BaseModel):
    authenticated: bool = True
    user: UserProfile = UserProfile()


@router.get("/session", response_model=SessionResponse)
def get_session() -> SessionResponse:
    return SessionResponse()


@router.post("/login", response_model=SessionResponse)
def login() -> SessionResponse:
    return SessionResponse()


@router.post("/register", response_model=SessionResponse)
def register() -> SessionResponse:
    return SessionResponse()


@router.post("/csrf", response_model=SessionResponse)
def csrf() -> SessionResponse:
    return SessionResponse()


@router.post("/logout")
def logout() -> dict[str, str]:
    return {"status": "ok"}
