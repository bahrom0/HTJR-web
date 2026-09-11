from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1.router import router as api_router
from app.core.database import Database
from app.core.errors import ApiError, ErrorEnvelope, api_error_handler
from app.core.logging import configure_logging
from app.core.settings import settings
from app.core.supabase_storage import SupabaseStorage
from app.repositories.jobs import JobRepository
from app.web_static import mount_web_client

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    configure_logging()
    application.state.settings = settings
    application.state.database = Database(settings.database_path)
    try:
        application.state.database.migrate()
    except Exception as e:
        logger.warning("Database migration note: %s", e)
    application.state.jobs = JobRepository(application.state.database)
    application.state.storage = SupabaseStorage(
        settings.supabase_url,
        settings.supabase_key,
        settings.supabase_bucket,
        local_fallback_dir=settings.storage_root,
    )
    yield


def create_app(*, web_dist: Path | None = None) -> FastAPI:
    application = FastAPI(
        title="Tajik HTR Studio API",
        version="1.0.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def add_request_id(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
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
        request_id = getattr(request.state, "request_id", "unknown")
        logger.exception(
            "request_failed request_id=%s error_type=%s",
            request_id,
            type(error).__name__,
        )
        payload = ErrorEnvelope(
            code="internal_error",
            message=str(error) if settings.environment == "development" else "An internal error occurred.",
            retryable=False,
            request_id=request_id,
        )
        return JSONResponse(status_code=500, content=payload.model_dump())

    application.include_router(api_router)

    configured_web_dist = web_dist or _web_dist_from_environment()
    if configured_web_dist is not None:
        mount_web_client(application, configured_web_dist)
    return application


def _web_dist_from_environment() -> Path | None:
    configured = os.environ.get("HTR_WEB_DIST")
    if not configured:
        return None
    return Path(configured).resolve()


app = create_app()
