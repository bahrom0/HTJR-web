from __future__ import annotations

import asyncio
import re
from collections.abc import AsyncIterator
from datetime import datetime
from time import monotonic
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AuthenticatedSession, require_session
from app.core.errors import ApiError
from app.repositories.jobs import JobEvent, JobNotFound, TERMINAL_STATES
from app.services.access import AccessDenied

router = APIRouter(tags=["events"])
LAST_EVENT_ID_PATTERN = re.compile(r"^[0-9]{1,19}$")
MAX_EVENT_SEQUENCE = 2**63 - 1
STREAM_SETTLED_STATES = TERMINAL_STATES | {"failed_retryable"}

JobState = Literal[
    "queued",
    "running",
    "awaiting_region_review",
    "completed",
    "partial",
    "failed_retryable",
    "failed_terminal",
    "cancelled",
]
JobStage = Literal[
    "queued",
    "uploading",
    "validating",
    "preprocessing",
    "detecting_regions",
    "awaiting_region_review",
    "recognizing_lines",
    "assembling",
    "suggesting",
    "ready_for_review",
    "completed",
]
JobEventType = Literal[
    "queued",
    "claimed",
    "stage_progress",
    "stage_completed",
    "stage_partial",
    "awaiting_region_review",
    "regions_confirmed",
    "cancellation_requested",
    "cancelled",
    "failed_retryable",
    "failed_terminal",
    "partial",
    "completed",
    "recovered",
    "retry_exhausted",
    "retried",
]


class JobEventPayload(BaseModel):
    """Content-safe, persisted projection sent to browsers over SSE."""

    model_config = ConfigDict(extra="forbid")

    job_id: UUID
    sequence: int = Field(ge=1)
    event_type: JobEventType
    state: JobState
    stage: JobStage
    processed_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    cancellation_requested: bool
    error_code: str | None
    error_retryable: bool
    can_cancel: bool
    can_retry: bool
    created_at: datetime


def _payload(event: JobEvent) -> JobEventPayload:
    return JobEventPayload(
        job_id=event.job_id,
        sequence=event.sequence,
        event_type=event.event_type,
        state=event.state,
        stage=event.stage,
        processed_count=event.processed_count,
        total_count=event.total_count,
        attempt=event.attempt,
        max_attempts=event.max_attempts,
        cancellation_requested=event.cancellation_requested,
        error_code=event.error_code,
        error_retryable=event.error_retryable,
        can_cancel=event.can_cancel,
        can_retry=event.can_retry,
        created_at=event.created_at,
    )


def encode_job_event(event: JobEvent) -> bytes:
    data = _payload(event).model_dump_json()
    return f"id: {event.sequence}\nevent: job\ndata: {data}\n\n".encode("utf-8")


def _header_cursor(last_event_id: str | None) -> int:
    if last_event_id is None or last_event_id == "":
        return 0
    if not LAST_EVENT_ID_PATTERN.fullmatch(last_event_id):
        raise ApiError(400, "last_event_id_invalid", "Last-Event-ID must be a non-negative event sequence.")
    cursor = int(last_event_id)
    if cursor > MAX_EVENT_SEQUENCE:
        raise ApiError(400, "last_event_id_invalid", "Last-Event-ID must be a non-negative event sequence.")
    return cursor


async def stream_job_events(
    request: Request,
    *,
    owner_session_id: str,
    job_id: str,
    cursor: int,
    session_token: str | None,
) -> AsyncIterator[bytes]:
    repository = request.app.state.jobs
    heartbeat_seconds = request.app.state.settings.sse_heartbeat_seconds
    poll_seconds = request.app.state.settings.sse_poll_seconds
    next_heartbeat = monotonic() + heartbeat_seconds

    while True:
        if await request.is_disconnected():
            return
        try:
            events = await asyncio.to_thread(
                repository.list_events,
                owner_session_id,
                job_id,
                after_sequence=cursor,
            )
        except JobNotFound:
            return

        if events:
            for event in events:
                if await request.is_disconnected():
                    return
                cursor = event.sequence
                yield encode_job_event(event)
                if event.state in STREAM_SETTLED_STATES:
                    return
            continue

        try:
            job = await asyncio.to_thread(repository.get, owner_session_id, job_id)
        except JobNotFound:
            return
        if job.state in STREAM_SETTLED_STATES:
            return

        now = monotonic()
        if now >= next_heartbeat:
            try:
                await asyncio.to_thread(request.app.state.access.authenticate, session_token)
            except AccessDenied:
                return
            yield b": heartbeat\n\n"
            next_heartbeat = now + heartbeat_seconds

        await asyncio.sleep(min(poll_seconds, max(0.0, next_heartbeat - monotonic())))


@router.get("/events/jobs/{job_id}", include_in_schema=False)
async def job_events(
    job_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    after: int | None = Query(default=None, ge=0, le=MAX_EVENT_SEQUENCE),
) -> StreamingResponse:
    cursor = max(_header_cursor(last_event_id), after or 0)
    repository = request.app.state.jobs
    try:
        latest = await asyncio.to_thread(repository.latest_event_sequence, session.id, job_id)
    except JobNotFound as error:
        raise ApiError(404, "job_not_found", "The recognition job was not found.") from error
    if cursor > latest:
        raise ApiError(409, "event_cursor_ahead", "The resume cursor is ahead of the persisted job event stream.")

    content = stream_job_events(
        request,
        owner_session_id=session.id,
        job_id=job_id,
        cursor=cursor,
        session_token=request.cookies.get(request.app.state.settings.cookie_name),
    )
    return StreamingResponse(
        content,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
