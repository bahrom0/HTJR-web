from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.api.v1.router import router as api_router
from app.api.events import router as events_router
from app.core.errors import ApiError, ErrorEnvelope, api_error_handler
from app.core.logging import configure_logging
from app.core.database import Database
from app.core.settings import settings
from app.services.access import AccessService
from app.domain.readiness import ReadinessService
from app.core.storage import FileStorage
from app.repositories.jobs import JobRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_logging()
    application.state.settings = settings
    application.state.database = Database(settings.database_path)
    application.state.database.migrate()
    application.state.jobs = JobRepository(application.state.database)
    application.state.readiness = ReadinessService(application.state.database, settings)
    application.state.access = AccessService(application.state.database, settings)
    application.state.storage = FileStorage(settings.storage_root)
    yield


def create_app() -> FastAPI:
    application = FastAPI(title="Tajik HTR Studio API", version="1.0.0", lifespan=lifespan, docs_url=None, redoc_url=None)

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        logger.info("request_complete method=%s path=%s status=%s request_id=%s", request.method, request.url.path, response.status_code, request.state.request_id)
        return response

    @application.exception_handler(ApiError)
    async def handle_api_error(request: Request, error: ApiError) -> JSONResponse:
        return await api_error_handler(request, error)

    @application.exception_handler(RequestValidationError)
    async def handle_request_validation_error(request: Request, _error: RequestValidationError) -> JSONResponse:
        request_id = getattr(request.state, "request_id", "unknown")
        payload = ErrorEnvelope(
            code="request_validation_failed",
            message="The request payload is invalid.",
            retryable=False,
            request_id=request_id,
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @application.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, error: Exception) -> JSONResponse:
        # Keep the response generic, but retain the traceback in the server
        # log.  The previous error-level message only recorded the exception
        # type, which made worker/API failures impossible to diagnose.  Do not
        # log request bodies, cookies, image data, or recognized text.
        logger.exception(
            "request_failed request_id=%s error_type=%s",
            request.state.request_id,
            type(error).__name__,
        )
        payload = ErrorEnvelope(code="internal_error", message="An internal error occurred.", retryable=False, request_id=request.state.request_id)
        return JSONResponse(status_code=500, content=payload.model_dump())

    application.include_router(api_router)
    application.include_router(events_router)
    return application


app = create_app()
