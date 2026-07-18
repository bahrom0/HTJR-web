from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Header, Request
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import AuthenticatedSession, require_mutation_session, require_session
from app.core.errors import ApiError
from app.repositories.jobs import (
    InvalidJobState,
    Job,
    JobNotFound,
    PageNotReady,
    QueueFull,
    RetryLimitReached,
)

router = APIRouter(tags=["jobs"])
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class CreateJobRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    priority: int = Field(default=0, ge=-10, le=10)


class JobResponse(BaseModel):
    id: str
    document_id: str
    page_id: str
    state: str
    stage: str
    priority: int
    processed_count: int
    total_count: int
    attempt: int
    max_attempts: int
    cancellation_requested: bool
    error_code: str | None
    error_retryable: bool
    revision: int
    created_at: str
    updated_at: str
    duplicate: bool = False


def _response(job: Job, *, duplicate: bool = False) -> JobResponse:
    return JobResponse(
        id=job.id,
        document_id=job.document_id,
        page_id=job.page_id,
        state=job.state,
        stage=job.stage,
        priority=job.priority,
        processed_count=job.processed_count,
        total_count=job.total_count,
        attempt=job.attempts,
        max_attempts=job.max_attempts,
        cancellation_requested=job.cancellation_requested_at is not None,
        error_code=job.error_code,
        error_retryable=job.error_retryable,
        revision=job.revision,
        created_at=job.created_at,
        updated_at=job.updated_at,
        duplicate=duplicate,
    )


def _not_found(error: JobNotFound) -> ApiError:
    return ApiError(404, "job_or_page_not_found", "The page or recognition job was not found.")


@router.post("/pages/{page_id}/recognition-jobs", response_model=JobResponse, status_code=201)
def create_job(
    page_id: str,
    payload: CreateJobRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> JobResponse:
    if idempotency_key is None or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ApiError(400, "idempotency_key_invalid", "A 16-128 character idempotency key is required.")
    try:
        job, duplicate = request.app.state.jobs.enqueue(
            session.id,
            page_id,
            idempotency_key,
            priority=payload.priority,
            capacity=request.app.state.settings.job_queue_capacity,
            max_attempts=request.app.state.settings.job_max_attempts,
        )
    except JobNotFound as error:
        raise _not_found(error) from error
    except PageNotReady as error:
        raise ApiError(409, "page_not_prepared", "The page must be prepared before recognition.") from error
    except QueueFull as error:
        raise ApiError(429, "job_queue_full", "The recognition queue is full; retry later.", True) from error
    return _response(job, duplicate=duplicate)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request, session: AuthenticatedSession = Depends(require_session)) -> JobResponse:
    try:
        return _response(request.app.state.jobs.get(session.id, job_id))
    except JobNotFound as error:
        raise _not_found(error) from error


@router.post("/jobs/{job_id}/cancel", response_model=JobResponse)
def cancel_job(job_id: str, request: Request, session: AuthenticatedSession = Depends(require_mutation_session)) -> JobResponse:
    try:
        return _response(request.app.state.jobs.request_cancel(session.id, job_id))
    except JobNotFound as error:
        raise _not_found(error) from error
    except InvalidJobState as error:
        raise ApiError(409, "job_not_cancellable", "The job cannot be cancelled in its current state.") from error


@router.post("/jobs/{job_id}/retry", response_model=JobResponse)
def retry_job(job_id: str, request: Request, session: AuthenticatedSession = Depends(require_mutation_session)) -> JobResponse:
    try:
        return _response(request.app.state.jobs.retry(session.id, job_id))
    except JobNotFound as error:
        raise _not_found(error) from error
    except RetryLimitReached as error:
        raise ApiError(409, "retry_limit_reached", "The retry limit has been reached.") from error
    except InvalidJobState as error:
        raise ApiError(409, "job_not_retryable", "Only a retryable failed job can be retried.") from error
