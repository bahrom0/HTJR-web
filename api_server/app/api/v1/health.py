from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.schemas.contracts import HealthLive

router = APIRouter(tags=["health"])


class HealthReady(BaseModel):
    status: str
    code: str


@router.get("/health/live", response_model=HealthLive)
async def get_live_health(request: Request) -> HealthLive:
    return HealthLive(status="ok", request_id=request.state.request_id)


@router.get("/health/ready", response_model=HealthReady)
async def get_ready_health(request: Request):
    readiness = request.app.state.readiness.pipeline_check()
    payload = HealthReady(status="ready" if readiness.is_ready else "unavailable", code=readiness.code)
    if readiness.is_ready:
        return payload
    return JSONResponse(status_code=503, content=payload.model_dump())
