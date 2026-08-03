from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    """Strict base model for the public API v1 transport contract."""

    model_config = ConfigDict(extra="forbid")


class ApiErrorEnvelope(ContractModel):
    code: str = Field(min_length=1)
    message: str = Field(min_length=1)
    retryable: bool
    request_id: str = Field(min_length=1)


class ResourceRef(ContractModel):
    id: UUID
    created_at: datetime
    updated_at: datetime


class RevisionMutation(ContractModel):
    revision: int = Field(ge=1)


class AccountProfile(ContractModel):
    id: UUID
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=2, max_length=100)
    created_at: datetime
    updated_at: datetime


class AccessSession(ContractModel):
    authenticated: Literal[True] = True
    expires_at: datetime
    csrf_token: str | None = None
    user: AccountProfile


class AccountRegisterRequest(ContractModel):
    email: str = Field(min_length=3, max_length=254)
    name: str = Field(min_length=2, max_length=100)
    password: str = Field(min_length=12, max_length=128)


class AccountLoginRequest(ContractModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ProfilePatch(ContractModel):
    name: str = Field(min_length=2, max_length=100)


class AccountSessionItem(ContractModel):
    id: UUID
    created_at: datetime
    expires_at: datetime
    last_seen_at: datetime
    user_agent: str
    current: bool


class AccountSessionList(ContractModel):
    items: list[AccountSessionItem]


class RevokeSessionsResponse(ContractModel):
    revoked_count: int = Field(ge=0)


class Document(ResourceRef):
    title: str = Field(min_length=1, max_length=240)
    status: Literal["draft", "processing", "review", "ready", "failed"]
    revision: int = Field(ge=1)


class DocumentList(ContractModel):
    items: list[Document]
    next_cursor: str | None = None


class DocumentPatch(RevisionMutation):
    title: str | None = Field(default=None, min_length=1, max_length=240)


class Page(ResourceRef):
    document_id: UUID
    position: int = Field(ge=0)
    revision: int = Field(ge=1)


class PageList(ContractModel):
    items: list[Page]


class PagePatch(RevisionMutation):
    position: int = Field(ge=0)


class RecognitionJob(ResourceRef):
    document_id: UUID
    page_id: UUID
    state: Literal[
        "queued",
        "running",
        "awaiting_region_review",
        "completed",
        "partial",
        "failed_retryable",
        "failed_terminal",
        "cancelled",
    ]
    stage: str = Field(min_length=1)
    processed_count: int = Field(ge=0)
    total_count: int = Field(ge=0)
    attempt: int = Field(ge=0)
    max_attempts: int = Field(ge=1)
    cancellation_requested: bool
    error_code: str | None = None
    error_retryable: bool = False
    revision: int = Field(ge=1)


class PolygonPoint(ContractModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class RecognitionRegion(ResourceRef):
    page_id: UUID
    polygon: list[PolygonPoint] = Field(min_length=4)
    position: int = Field(ge=0)
    revision: int = Field(ge=1)


class RegionList(ContractModel):
    items: list[RecognitionRegion]


class RegionCreate(ContractModel):
    page_id: UUID
    polygon: list[PolygonPoint] = Field(min_length=4)
    position: int = Field(ge=0)
    idempotency_key: str = Field(min_length=16, max_length=128)


class RegionPatch(RevisionMutation):
    polygon: list[PolygonPoint] | None = Field(default=None, min_length=4)
    position: int | None = Field(default=None, ge=0)


class TextLine(ResourceRef):
    region_id: UUID
    position: int = Field(ge=0)
    raw_text: str
    suggested_text: str | None = None
    confirmed_text: str | None = None
    revision: int = Field(ge=1)


class TextLineList(ContractModel):
    items: list[TextLine]


class TextLinePatch(RevisionMutation):
    suggested_text: str | None = None
    confirmed_text: str | None = None


class Correction(ResourceRef):
    text_line_id: UUID
    from_version_id: UUID
    to_version_id: UUID


class CorrectionList(ContractModel):
    items: list[Correction]


class CorrectionCreate(RevisionMutation):
    confirmed_text: str
    idempotency_key: str = Field(min_length=16, max_length=128)


class ExportCreate(ContractModel):
    format: Literal["txt", "pdf", "searchable_pdf", "docx"]
    idempotency_key: str = Field(min_length=16, max_length=128)


class ExportArtifact(ResourceRef):
    document_id: UUID
    format: Literal["txt", "pdf", "searchable_pdf", "docx"]
    status: Literal["queued", "running", "ready", "failed"]
    download_url: str | None = None


class Diagnostics(ContractModel):
    status: Literal["ok", "degraded"]
    checked_at: datetime


class HealthLive(ContractModel):
    status: Literal["ok"]
    request_id: str
