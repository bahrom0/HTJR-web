from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict


class ErrorEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    message: str
    retryable: bool
    request_id: str


class ApiError(Exception):
    def __init__(self, status_code: int, code: str, message: str, retryable: bool = False) -> None:
        self.status_code = status_code
        self.code = code
        self.message = message
        self.retryable = retryable


async def api_error_handler(request: Request, error: ApiError) -> JSONResponse:
    request_id = getattr(request.state, "request_id", "unknown")
    payload = ErrorEnvelope(code=error.code, message=error.message, retryable=error.retryable, request_id=request_id)
    return JSONResponse(status_code=error.status_code, content=payload.model_dump())
