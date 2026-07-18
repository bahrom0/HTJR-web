from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResourceRef(ContractModel):
    id: UUID
    created_at: datetime
    updated_at: datetime


class AccessSession(ContractModel):
    id: UUID
    expires_at: datetime


class Document(ResourceRef):
    title: str = Field(min_length=1, max_length=240)
    status: Literal["draft", "processing", "review", "ready", "failed"]
    revision: int = Field(ge=0)


class Page(ResourceRef):
    document_id: UUID
    position: int = Field(ge=0)


class RecognitionJob(ResourceRef):
    document_id: UUID
    stage: str
    status: str


class RecognitionRegion(ResourceRef):
    page_id: UUID
    position: int = Field(ge=0)


class TextLine(ResourceRef):
    region_id: UUID
    raw_text: str
    confirmed_text: str | None = None


class Correction(ResourceRef):
    text_line_id: UUID
    before: str
    after: str


class ExportArtifact(ResourceRef):
    document_id: UUID
    format: Literal["txt", "pdf", "searchable_pdf", "docx"]


class Diagnostics(ContractModel):
    status: Literal["ok", "degraded"]
    checked_at: datetime


class HealthLive(ContractModel):
    status: Literal["ok"]
    request_id: str
