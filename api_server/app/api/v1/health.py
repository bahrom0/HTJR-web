from __future__ import annotations

from fastapi import APIRouter, Request

from app.schemas.contracts import HealthLive

router = APIRouter(tags=["health"])


@router.get("/health/live", response_model=HealthLive)
async def get_live_health(request: Request) -> HealthLive:
    return HealthLive(status="ok", request_id=request.state.request_id)
