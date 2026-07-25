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
    PagePreparationNotConfirmed,
    PageNotReady,
    QueueFull,
    RetryLimitReached,
)
from app.repositories.recognition import ManualFallbackUnavailable, RecognitionInputInvalid, RecognitionRepository

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


class ManualFallbackRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    raw_text: str = Field(max_length=10_000)


class RecognitionResultResponse(BaseModel):
    job_id: str
    document_id: str
    page_id: str
    raw_text: str
    is_partial: bool


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
    except PagePreparationNotConfirmed as error:
        raise ApiError(
            409,
            "page_preparation_not_confirmed",
            "Confirm the current preparation recipe before recognition.",
        ) from error
    except QueueFull as error:
        raise ApiError(429, "job_queue_full", "The recognition queue is full; retry later.", True) from error
    return _response(job, duplicate=duplicate)


@router.get("/jobs/{job_id}", response_model=JobResponse)
def get_job(job_id: str, request: Request, session: AuthenticatedSession = Depends(require_session)) -> JobResponse:
    try:
        return _response(request.app.state.jobs.get(session.id, job_id))
    except JobNotFound as error:
        raise _not_found(error) from error


@router.get("/jobs/{job_id}/result", response_model=RecognitionResultResponse)
def get_recognition_result(
    job_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> RecognitionResultResponse:
    try:
        job = request.app.state.jobs.get(session.id, job_id)
    except JobNotFound as error:
        raise _not_found(error) from error

    with request.app.state.database.connect() as connection:
        row = connection.execute(
            """SELECT pr.raw_text,pr.is_partial
               FROM page_raw_results pr
               JOIN recognition_runs r ON r.id=pr.recognition_run_id
               WHERE r.job_id=? AND pr.owner_session_id=?
               ORDER BY pr.created_at DESC LIMIT 1""",
            (job.id, session.id),
        ).fetchone()
    if row is None:
        raise ApiError(409, "result_not_ready", "The recognized text is not ready yet.", True)
    return RecognitionResultResponse(
        job_id=job.id,
        document_id=job.document_id,
        page_id=job.page_id,
        raw_text=str(row["raw_text"]),
        is_partial=bool(row["is_partial"]),
    )


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


@router.post("/jobs/{job_id}/run-regions/{run_region_id}/manual-fallback", response_model=JobResponse)
def record_manual_fallback(
    job_id: str,
    run_region_id: str,
    payload: ManualFallbackRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> JobResponse:
    recognition = RecognitionRepository(request.app.state.database, request.app.state.storage)
    try:
        run_id, is_partial = recognition.record_manual_fallback(
            session.id,
            job_id,
            run_region_id,
            raw_text=payload.raw_text,
        )
        if is_partial:
            return _response(request.app.state.jobs.get(session.id, job_id))
        return _response(request.app.state.jobs.complete_manual_fallback(session.id, job_id, run_id))
    except JobNotFound as error:
        raise _not_found(error) from error
    except (ManualFallbackUnavailable, RecognitionInputInvalid) as error:
        raise ApiError(409, str(error), "The failed line is not available for manual fallback.") from error
    except InvalidJobState as error:
        raise ApiError(409, str(error), "Manual fallback cannot finalize the job yet.") from error
