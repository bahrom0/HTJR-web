from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.api.dependencies import AuthenticatedSession, require_mutation_session, require_session
from app.core.errors import ApiError
from app.repositories.jobs import JobNotFound, RegionReviewConflict
from app.repositories.regions import PageNotFound, RegionRepository, RegionRevisionConflict

router = APIRouter(tags=["regions"])


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class RegionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str | None = None
    polygon: list[Point] = Field(min_length=4, max_length=4)
    reading_order: int = Field(ge=0, le=100_000)
    source: Literal["craft", "kraken", "gemini_openrouter", "manual", "adjusted"]
    flags: list[str] = Field(default_factory=list, max_length=32)
    detector_version: str | None = Field(default=None, max_length=128)
    detector_score: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def valid_polygon(self) -> RegionInput:
        area = 0.0
        for index, point in enumerate(self.polygon):
            next_point = self.polygon[(index + 1) % len(self.polygon)]
            area += point.x * next_point.y - next_point.x * point.y
        if abs(area) < 0.000001:
            raise ValueError("polygon must have non-zero area")
        if self.source == "craft" and (self.detector_version is None or self.detector_score is None):
            raise ValueError("craft regions require detector provenance and score")
        if self.source in {"kraken", "gemini_openrouter"} and self.detector_version is None:
            raise ValueError("kraken regions require detector provenance")
        return self


class ReplaceRegionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    regions: list[RegionInput] = Field(max_length=10_000)

    @model_validator(mode="after")
    def contiguous_order(self) -> ReplaceRegionsRequest:
        if sorted(region.reading_order for region in self.regions) != list(range(len(self.regions))):
            raise ValueError("reading_order must be contiguous starting from zero")
        return self


class ConfirmRegionsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    job_id: str | None = None
    job_revision: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def job_confirmation_is_complete(self) -> ConfirmRegionsRequest:
        if (self.job_id is None) != (self.job_revision is None):
            raise ValueError("job_id and job_revision must be sent together")
        return self


class RegionResponse(BaseModel):
    id: str
    polygon: list[Point]
    reading_order: int
    revision: int
    source: Literal["craft", "kraken", "gemini_openrouter", "manual", "adjusted"]
    flags: list[str]
    detector_version: str | None
    detector_score: float | None


class RegionsResponse(BaseModel):
    page_id: str
    revision: int
    confirmed: bool
    regions: list[RegionResponse]
    resumed_job_id: str | None = None


def _repository(request: Request) -> RegionRepository:
    return RegionRepository(request.app.state.database)


def _not_found(error: PageNotFound) -> ApiError:
    return ApiError(404, "page_not_found", "The page was not found.")


@router.get("/pages/{page_id}/regions", response_model=RegionsResponse)
def get_regions(
    page_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> RegionsResponse:
    try:
        revision, confirmed_revision, regions = _repository(request).list(session.id, page_id)
    except PageNotFound as error:
        raise _not_found(error) from error
    return RegionsResponse(
        page_id=page_id,
        revision=revision,
        confirmed=confirmed_revision == revision,
        regions=[RegionResponse.model_validate(region) for region in regions],
    )


@router.put("/pages/{page_id}/regions", response_model=RegionsResponse)
def replace_regions(
    page_id: str,
    payload: ReplaceRegionsRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> RegionsResponse:
    values = [region.model_dump() for region in payload.regions]
    try:
        _repository(request).replace(session.id, page_id, payload.revision, values)
        revision, confirmed_revision, regions = _repository(request).list(session.id, page_id)
    except PageNotFound as error:
        raise _not_found(error) from error
    except RegionRevisionConflict as error:
        raise ApiError(409, "revision_conflict", "The page changed; refresh regions before saving.", True) from error
    return RegionsResponse(
        page_id=page_id,
        revision=revision,
        confirmed=confirmed_revision == revision,
        regions=[RegionResponse.model_validate(region) for region in regions],
    )


@router.post("/pages/{page_id}/regions/confirm", response_model=RegionsResponse)
def confirm_regions(
    page_id: str,
    payload: ConfirmRegionsRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> RegionsResponse:
    try:
        resumed_job_id = None
        if payload.job_id is None:
            _repository(request).confirm(session.id, page_id, payload.revision)
        else:
            _, job = request.app.state.jobs.confirm_regions_and_resume(
                session.id,
                page_id,
                expected_page_revision=payload.revision,
                job_id=payload.job_id,
                expected_job_revision=payload.job_revision,
            )
            resumed_job_id = job.id
        revision, confirmed_revision, regions = _repository(request).list(session.id, page_id)
    except PageNotFound as error:
        raise _not_found(error) from error
    except JobNotFound as error:
        raise ApiError(404, "job_or_page_not_found", "The page or recognition job was not found.") from error
    except RegionRevisionConflict as error:
        raise ApiError(409, "revision_conflict", "The page changed; refresh regions before confirming.", True) from error
    except RegionReviewConflict as error:
        raise ApiError(409, str(error), "The region review state changed; refresh before confirming.", True) from error
    return RegionsResponse(
        page_id=page_id,
        revision=revision,
        confirmed=confirmed_revision == revision,
        regions=[RegionResponse.model_validate(region) for region in regions],
        resumed_job_id=resumed_job_id,
    )
