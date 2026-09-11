from __future__ import annotations

import hashlib
import io
import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import PurePath
from typing import Any
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, File, UploadFile
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from PIL import Image, ImageOps

from app.api.dependencies import AuthenticatedSession, require_mutation_session, require_session
from app.core.errors import ApiError
from app.ml.gemini_runtime import GeminiOcrRuntime

logger = logging.getLogger(__name__)
from app.services.images import (
    PIPELINE_VERSION,
    QUALITY_THRESHOLD_VERSION,
    assess_quality,
    canonical_recipe,
    encode_prepared,
    prepare_image,
    recipe_hash,
    validate_image,
)

router = APIRouter(tags=["documents"])
IDEMPOTENCY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


class AssetResponse(BaseModel):
    id: str
    media_type: str
    width: int
    height: int
    preview_url: str


class UploadResponse(BaseModel):
    document_id: str
    page_id: str
    asset: AssetResponse
    duplicate: bool = False


class Point(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class Crop(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def within_bounds(self):
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("Crop must remain inside normalized image bounds")
        return self


class PreprocessRecipe(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rotation_degrees: int = 0
    crop: Crop | None = None
    perspective: list[Point] | None = None
    max_edge: int = Field(default=3000, ge=512, le=4096)

    @model_validator(mode="after")
    def validate_geometry(self):
        if self.rotation_degrees not in (0, 90, 180, 270):
            raise ValueError("rotation_degrees must be 0, 90, 180, or 270")
        if self.perspective is not None and len(self.perspective) != 4:
            raise ValueError("perspective must contain exactly four points")
        return self


class PreparationResponse(BaseModel):
    page_id: str
    prepared_asset: AssetResponse
    pipeline_version: str
    recipe_hash: str
    quality_threshold_version: str
    quality_metrics: dict[str, float | int]
    quality_warnings: list[str]
    duplicate: bool = False


class PagePreparationState(BaseModel):
    document_id: str
    page_id: str
    revision: int
    source_asset: AssetResponse
    prepared_asset: AssetResponse | None = None
    recipe: PreprocessRecipe | None = None
    recipe_hash: str | None = None
    quality_threshold_version: str | None = None
    quality_metrics: dict[str, float | int] | None = None
    quality_warnings: list[str] = Field(default_factory=list)
    confirmed: bool = False


class ConfirmPreparationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class ConfirmPreparationResponse(BaseModel):
    page_id: str
    revision: int
    recipe_hash: str
    confirmed_at: str


class DocumentSummaryResponse(BaseModel):
    id: str
    title: str
    status: str
    revision: int
    page_count: int
    created_at: str
    updated_at: str
    latest_job_id: str | None = None
    preview_url: str | None = None
    preview_text: str | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentSummaryResponse]


class DocumentPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=255)


class DocumentDeleteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    revision: int = Field(ge=1)


class EditorLineResponse(BaseModel):
    id: str
    page_id: str
    position: int
    raw_text: str
    text: str
    status: str
    revision: int
    crop_url: str


class EditorDocumentResponse(BaseModel):
    document: DocumentSummaryResponse
    lines: list[EditorLineResponse]


class EditorDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(max_length=10_000)
    revision: int = Field(ge=1)


class EditorConfirmRequest(EditorDraftRequest):
    idempotency_key: str = Field(min_length=16, max_length=128)


def _safe_filename(raw: str | None) -> str | None:
    if not raw:
        return None
    decoded = unquote(raw)[:1024].replace("\\", "/")
    name = PurePath(decoded).name
    cleaned = "".join(char for char in name if char.isprintable() and char not in "\r\n\0").strip()
    return cleaned[:255] or None


def _existing_upload(request: Request, owner: str, key: str) -> UploadResponse | None:
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            """SELECT ui.document_id,ui.page_id,a.id asset_id,a.media_type,a.width,a.height
               FROM upload_idempotency ui JOIN assets a ON a.id=ui.asset_id
               WHERE ui.owner_session_id=? AND ui.idempotency_key=?""",
            (owner, key),
        ).fetchone()
    if row is None:
        return None
    return UploadResponse(
        document_id=row["document_id"], page_id=row["page_id"], duplicate=True,
        asset=AssetResponse(id=row["asset_id"], media_type=row["media_type"], width=row["width"], height=row["height"], preview_url=f"/api/v1/assets/{row['asset_id']}/preview"),
    )


@router.post("/documents", response_model=UploadResponse, status_code=201)
async def create_document(
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    original_filename: str | None = Header(default=None, alias="X-Original-Filename"),
) -> UploadResponse:
    if idempotency_key is None or not IDEMPOTENCY_PATTERN.fullmatch(idempotency_key):
        raise ApiError(400, "idempotency_key_invalid", "A 16-128 character idempotency key is required.")
    existing = _existing_upload(request, session.id, idempotency_key)
    if existing:
        return existing
    settings = request.app.state.settings
    declared_type = request.headers.get("content-type", "")
    content_length = request.headers.get("content-length")
    if content_length and (not content_length.isdigit() or int(content_length) > settings.upload_max_bytes):
        raise ApiError(413, "upload_too_large", "The image exceeds the upload byte limit.")
    try:
        staged = await request.app.state.storage.stage_stream(request.stream(), max_bytes=settings.upload_max_bytes)
    except OverflowError as error:
        raise ApiError(413, "upload_too_large", "The image exceeds the upload byte limit.") from error
    except Exception as error:
        raise ApiError(400, "upload_interrupted", "The upload was interrupted; it can be retried.", True) from error
    if staged.byte_size == 0:
        request.app.state.storage.discard_temporary(staged.storage_key)
        raise ApiError(422, "upload_empty", "The uploaded image is empty.")
    try:
        validated = validate_image(staged.path, declared_type, max_pixels=settings.image_max_pixels, max_dimension=settings.image_max_dimension)
    except Exception:
        request.app.state.storage.discard_temporary(staged.storage_key)
        raise

    now = datetime.now(UTC).isoformat()
    document_id, page_id, asset_id = str(uuid4()), str(uuid4()), str(uuid4())
    filename = _safe_filename(original_filename)
    title = PurePath(filename).stem[:160] if filename else "Новый документ"
    committed = False
    try:
        with request.app.state.database.transaction(immediate=True) as connection:
            duplicate = connection.execute("SELECT 1 FROM upload_idempotency WHERE owner_session_id=? AND idempotency_key=?", (session.id, idempotency_key)).fetchone()
            if duplicate:
                raise sqlite3.IntegrityError("duplicate idempotency key")
            connection.execute("INSERT INTO documents(id,owner_session_id,title,created_at,updated_at) VALUES (?,?,?,?,?)", (document_id, session.id, title, now, now))
            connection.execute(
                """INSERT INTO assets(id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,original_filename,kind,width,height)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (asset_id, session.id, document_id, staged.storage_key, staged.sha256, staged.byte_size, validated.media_type, "temporary", now, filename, "original", validated.width, validated.height),
            )
            connection.execute("INSERT INTO pages(id,document_id,source_asset_id,page_index,created_at,updated_at) VALUES (?,?,?,0,?,?)", (page_id, document_id, asset_id, now, now))
            connection.execute("INSERT INTO upload_idempotency(owner_session_id,idempotency_key,document_id,page_id,asset_id,created_at) VALUES (?,?,?,?,?,?)", (session.id, idempotency_key, document_id, page_id, asset_id, now))
            request.app.state.storage.commit(staged)
            committed = True
            connection.execute("UPDATE assets SET state='committed',committed_at=? WHERE id=?", (now, asset_id))
    except sqlite3.IntegrityError:
        if committed:
            request.app.state.storage.discard_committed(staged.storage_key)
        else:
            request.app.state.storage.discard_temporary(staged.storage_key)
        existing = _existing_upload(request, session.id, idempotency_key)
        if existing:
            return existing
        raise ApiError(409, "upload_conflict", "The upload could not be committed; retry with the same key.", True)
    except Exception:
        if committed:
            request.app.state.storage.discard_committed(staged.storage_key)
        else:
            request.app.state.storage.discard_temporary(staged.storage_key)
        raise
    return UploadResponse(document_id=document_id, page_id=page_id, asset=AssetResponse(id=asset_id, media_type=validated.media_type, width=validated.width, height=validated.height, preview_url=f"/api/v1/assets/{asset_id}/preview"))


def _preparation_from_row(row, *, duplicate: bool) -> PreparationResponse:
    return PreparationResponse(
        page_id=row["page_id"],
        prepared_asset=AssetResponse(id=row["prepared_asset_id"], media_type="image/png", width=row["width"], height=row["height"], preview_url=f"/api/v1/assets/{row['prepared_asset_id']}/preview"),
        pipeline_version=row["pipeline_version"], recipe_hash=row["recipe_hash"], quality_threshold_version=row["quality_threshold_version"],
        quality_metrics=json.loads(row["quality_metrics_json"]), quality_warnings=json.loads(row["quality_warnings_json"]), duplicate=duplicate,
    )


@router.get("/pages/{page_id}/preparation", response_model=PagePreparationState)
def get_page_preparation(
    page_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> PagePreparationState:
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            """SELECT p.id page_id,p.document_id,p.revision,p.preprocessing_recipe_hash,
                      p.preparation_confirmed_recipe_hash,
                      source.id source_asset_id,source.media_type source_media_type,
                      source.width source_width,source.height source_height,
                      prepared.id prepared_asset_id,prepared.media_type prepared_media_type,
                      prepared.width prepared_width,prepared.height prepared_height,
                      pr.recipe_json,pr.recipe_hash,pr.quality_threshold_version,
                      pr.quality_metrics_json,pr.quality_warnings_json
               FROM pages p
               JOIN documents d ON d.id=p.document_id
               JOIN assets source ON source.id=p.source_asset_id AND source.state='committed'
               LEFT JOIN assets prepared ON prepared.id=p.prepared_asset_id AND prepared.state='committed'
               LEFT JOIN preprocessing_runs pr ON pr.prepared_asset_id=p.prepared_asset_id
               WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
            (page_id, session.id),
        ).fetchone()
    if row is None:
        raise ApiError(404, "page_not_found", "The page was not found.")

    source_asset = AssetResponse(
        id=row["source_asset_id"],
        media_type=row["source_media_type"],
        width=row["source_width"],
        height=row["source_height"],
        preview_url=f"/api/v1/assets/{row['source_asset_id']}/preview",
    )
    if row["prepared_asset_id"] is None or row["recipe_json"] is None:
        return PagePreparationState(
            document_id=row["document_id"],
            page_id=row["page_id"],
            revision=row["revision"],
            source_asset=source_asset,
        )

    return PagePreparationState(
        document_id=row["document_id"],
        page_id=row["page_id"],
        revision=row["revision"],
        source_asset=source_asset,
        prepared_asset=AssetResponse(
            id=row["prepared_asset_id"],
            media_type=row["prepared_media_type"],
            width=row["prepared_width"],
            height=row["prepared_height"],
            preview_url=f"/api/v1/assets/{row['prepared_asset_id']}/preview",
        ),
        recipe=PreprocessRecipe.model_validate(json.loads(row["recipe_json"])),
        recipe_hash=row["recipe_hash"],
        quality_threshold_version=row["quality_threshold_version"],
        quality_metrics=json.loads(row["quality_metrics_json"]),
        quality_warnings=json.loads(row["quality_warnings_json"]),
        confirmed=row["preparation_confirmed_recipe_hash"] == row["recipe_hash"],
    )


@router.post("/pages/{page_id}/preparation/confirm", response_model=ConfirmPreparationResponse)
def confirm_page_preparation(
    page_id: str,
    payload: ConfirmPreparationRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> ConfirmPreparationResponse:
    now = datetime.now(UTC).isoformat()
    with request.app.state.database.transaction(immediate=True) as connection:
        page = connection.execute(
            """SELECT p.revision,p.preprocessing_recipe_hash
               FROM pages p JOIN documents d ON d.id=p.document_id
               WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
            (page_id, session.id),
        ).fetchone()
        if page is None:
            raise ApiError(404, "page_not_found", "The page was not found.")
        if page["preprocessing_recipe_hash"] is None:
            raise ApiError(409, "page_not_prepared", "Prepare the page before confirming it.")
        if page["revision"] != payload.revision:
            raise ApiError(409, "revision_conflict", "The page changed; refresh before confirming it.", True)
        connection.execute(
            """UPDATE pages
               SET preparation_confirmed_recipe_hash=?,preparation_confirmed_at=?,
                   revision=revision+1,updated_at=?
               WHERE id=?""",
            (page["preprocessing_recipe_hash"], now, now, page_id),
        )
        revision = page["revision"] + 1
    return ConfirmPreparationResponse(
        page_id=page_id,
        revision=revision,
        recipe_hash=page["preprocessing_recipe_hash"],
        confirmed_at=now,
    )


@router.post("/pages/{page_id}/prepare", response_model=PreparationResponse)
def prepare_page(page_id: str, recipe: PreprocessRecipe, request: Request, session: AuthenticatedSession = Depends(require_mutation_session)) -> PreparationResponse:
    with request.app.state.database.connect() as connection:
        source = connection.execute(
            """SELECT p.id page_id,a.id source_asset_id,a.storage_key,a.sha256
               FROM pages p JOIN documents d ON d.id=p.document_id JOIN assets a ON a.id=p.source_asset_id
               WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL AND a.state='committed'""",
            (page_id, session.id),
        ).fetchone()
    if source is None:
        raise ApiError(404, "page_not_found", "The page was not found.")
    recipe_data = recipe.model_dump(mode="json")
    recipe_json = canonical_recipe(recipe_data)
    digest = recipe_hash(source["sha256"], recipe_json)
    with request.app.state.database.connect() as connection:
        prior = connection.execute(
            """SELECT pr.*,a.width,a.height FROM preprocessing_runs pr JOIN assets a ON a.id=pr.prepared_asset_id
               WHERE pr.owner_session_id=? AND pr.page_id=? AND pr.recipe_hash=?""", (session.id, page_id, digest)
        ).fetchone()
    if prior:
        return _preparation_from_row(prior, duplicate=True)
    image = prepare_image(request.app.state.storage.resolve(source["storage_key"]), recipe_data, server_max_edge=request.app.state.settings.prepared_max_edge)
    metrics, warnings_out = assess_quality(image)
    prepared_bytes = encode_prepared(image)
    staged = request.app.state.storage.stage(io.BytesIO(prepared_bytes))
    now, asset_id, run_id = datetime.now(UTC).isoformat(), str(uuid4()), str(uuid4())
    committed = False
    try:
        with request.app.state.database.transaction(immediate=True) as connection:
            connection.execute(
                """INSERT INTO assets(id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,kind,width,height,parent_asset_id)
                   SELECT ?,?,p.document_id,?,?,?,?,?,?,?,?,?,? FROM pages p WHERE p.id=?""",
                (asset_id, session.id, staged.storage_key, staged.sha256, staged.byte_size, "image/png", "temporary", now, "prepared", image.width, image.height, source["source_asset_id"], page_id),
            )
            request.app.state.storage.commit(staged)
            committed = True
            connection.execute("UPDATE assets SET state='committed',committed_at=? WHERE id=?", (now, asset_id))
            connection.execute(
                """INSERT INTO preprocessing_runs(id,owner_session_id,page_id,source_asset_id,prepared_asset_id,pipeline_version,recipe_json,recipe_hash,quality_threshold_version,quality_metrics_json,quality_warnings_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                (run_id, session.id, page_id, source["source_asset_id"], asset_id, PIPELINE_VERSION, recipe_json, digest, QUALITY_THRESHOLD_VERSION, json.dumps(metrics, sort_keys=True), json.dumps(warnings_out), now),
            )
            connection.execute(
                "UPDATE pages SET prepared_asset_id=?,preprocessing_recipe_hash=?, "
                "preparation_confirmed_recipe_hash=NULL,preparation_confirmed_at=NULL, "
                "revision=revision+1,updated_at=? WHERE id=?",
                (asset_id, digest, now, page_id),
            )
    except sqlite3.IntegrityError:
        (request.app.state.storage.discard_committed if committed else request.app.state.storage.discard_temporary)(staged.storage_key)
        with request.app.state.database.connect() as connection:
            prior = connection.execute("SELECT pr.*,a.width,a.height FROM preprocessing_runs pr JOIN assets a ON a.id=pr.prepared_asset_id WHERE pr.owner_session_id=? AND pr.page_id=? AND pr.recipe_hash=?", (session.id, page_id, digest)).fetchone()
        if prior:
            return _preparation_from_row(prior, duplicate=True)
        raise ApiError(409, "preprocessing_conflict", "The preprocessing result conflicted; retry safely.", True)
    except Exception:
        (request.app.state.storage.discard_committed if committed else request.app.state.storage.discard_temporary)(staged.storage_key)
        raise
    return PreparationResponse(page_id=page_id, prepared_asset=AssetResponse(id=asset_id, media_type="image/png", width=image.width, height=image.height, preview_url=f"/api/v1/assets/{asset_id}/preview"), pipeline_version=PIPELINE_VERSION, recipe_hash=digest, quality_threshold_version=QUALITY_THRESHOLD_VERSION, quality_metrics=metrics, quality_warnings=warnings_out)


@router.get("/assets/{asset_id}/preview")
def preview_asset(asset_id: str, request: Request, max_edge: int = Query(default=1200, ge=128), session: AuthenticatedSession = Depends(require_session)) -> Response:
    bounded_edge = min(max_edge, request.app.state.settings.preview_max_edge)
    with request.app.state.database.connect() as connection:
        asset = connection.execute("SELECT storage_key,sha256 FROM assets WHERE id=? AND owner_session_id=? AND state='committed'", (asset_id, session.id)).fetchone()
    if asset is None:
        raise ApiError(404, "asset_not_found", "The image preview was not found.")
    etag = f'"{asset["sha256"][:24]}-{bounded_edge}"'
    headers = {"Cache-Control": "private, max-age=300, must-revalidate", "ETag": etag, "X-Content-Type-Options": "nosniff"}
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    try:
        with Image.open(request.app.state.storage.resolve(asset["storage_key"])) as source:
            image = ImageOps.exif_transpose(source).convert("RGB")
            image.thumbnail((bounded_edge, bounded_edge), Image.Resampling.LANCZOS)
            output = io.BytesIO()
            image.save(output, format="JPEG", quality=82, optimize=False, progressive=False)
    except (OSError, ValueError) as error:
        raise ApiError(422, "preview_decode_failed", "A safe preview could not be generated.") from error
    return Response(output.getvalue(), media_type="image/jpeg", headers=headers)


def _effective_document_status(job_state: str | None, line_count: int, confirmed_count: int) -> str:
    if job_state in {"queued", "running", "awaiting_worker", "cancelling"}:
        return "processing"
    if job_state in {"failed_retryable", "failed_terminal", "cancelled"}:
        return "failed"
    if job_state in {"completed", "partial"}:
        return "ready" if line_count > 0 and confirmed_count == line_count else "review"
    return "draft"


def _document_row(connection, owner: str, document_id: str | None = None, query: str = "", limit: int = 50):
    filters = ["d.owner_session_id=?", "d.deleted_at IS NULL"]
    values: list[object] = [owner]
    if document_id:
        filters.append("d.id=?")
        values.append(document_id)
    if query:
        filters.append("LOWER(d.title) LIKE ?")
        values.append(f"%{query.lower()}%")
    values.append(limit)
    return connection.execute(
        f"""SELECT d.id,d.title,d.status,d.revision,d.created_at,d.updated_at,
                   COUNT(DISTINCT p.id) page_count,
                   (SELECT j.id FROM recognition_jobs j WHERE j.document_id=d.id
                    ORDER BY j.updated_at DESC,j.created_at DESC LIMIT 1) latest_job_id,
                   (SELECT j.state FROM recognition_jobs j WHERE j.document_id=d.id
                    ORDER BY j.updated_at DESC,j.created_at DESC LIMIT 1) latest_job_state,
                   (SELECT COALESCE(p0.prepared_asset_id,p0.source_asset_id) FROM pages p0
                    WHERE p0.document_id=d.id ORDER BY p0.page_index LIMIT 1) preview_asset_id,
                   (SELECT SUBSTR(pr.raw_text,1,240) FROM page_raw_results pr
                    JOIN recognition_runs r ON r.id=pr.recognition_run_id
                    JOIN recognition_jobs j ON j.id=r.job_id
                    WHERE j.document_id=d.id ORDER BY pr.created_at DESC LIMIT 1) preview_text,
                   (SELECT COUNT(*) FROM text_lines tl JOIN recognition_regions rg ON rg.id=tl.region_id
                    JOIN pages ep ON ep.id=rg.page_id WHERE ep.document_id=d.id) line_count,
                   (SELECT COUNT(*) FROM text_lines tl JOIN recognition_regions rg ON rg.id=tl.region_id
                    JOIN pages ep ON ep.id=rg.page_id WHERE ep.document_id=d.id AND EXISTS(
                      SELECT 1 FROM text_versions tv WHERE tv.line_id=tl.id AND tv.kind='confirmed'
                    )) confirmed_count
            FROM documents d LEFT JOIN pages p ON p.document_id=d.id
            WHERE {" AND ".join(filters)}
            GROUP BY d.id ORDER BY d.updated_at DESC LIMIT ?""",
        tuple(values),
    ).fetchall()


def _document_response(row) -> DocumentSummaryResponse:
    asset_id = row["preview_asset_id"]
    return DocumentSummaryResponse(
        id=row["id"],
        title=row["title"],
        status=_effective_document_status(
            row["latest_job_state"], int(row["line_count"]), int(row["confirmed_count"])
        ),
        revision=int(row["revision"]),
        page_count=int(row["page_count"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
        latest_job_id=row["latest_job_id"],
        preview_url=f"/api/v1/assets/{asset_id}/preview?max_edge=720" if asset_id else None,
        preview_text=row["preview_text"],
    )


@router.get("/documents", response_model=DocumentListResponse)
def list_documents(
    request: Request,
    q: str = Query(default="", max_length=200),
    limit: int = Query(default=50, ge=1, le=100),
    session: AuthenticatedSession = Depends(require_session),
) -> DocumentListResponse:
    with request.app.state.database.connect() as connection:
        rows = _document_row(connection, session.id, query=q.strip(), limit=limit)
    return DocumentListResponse(items=[_document_response(row) for row in rows])


@router.get("/documents/{document_id}", response_model=DocumentSummaryResponse)
def get_document(
    document_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> DocumentSummaryResponse:
    with request.app.state.database.connect() as connection:
        rows = _document_row(connection, session.id, document_id=document_id, limit=1)
    if not rows:
        raise ApiError(404, "document_not_found", "The document was not found.")
    return _document_response(rows[0])


@router.patch("/documents/{document_id}", response_model=DocumentSummaryResponse)
def patch_document(
    document_id: str,
    payload: DocumentPatchRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> DocumentSummaryResponse:
    now = datetime.now(UTC).isoformat()
    with request.app.state.database.transaction(immediate=True) as connection:
        cursor = connection.execute(
            """UPDATE documents SET title=?,revision=revision+1,updated_at=?
               WHERE id=? AND owner_session_id=? AND revision=? AND deleted_at IS NULL""",
            (payload.title.strip(), now, document_id, session.id, payload.revision),
        )
        if cursor.rowcount != 1:
            owned = connection.execute(
                "SELECT 1 FROM documents WHERE id=? AND owner_session_id=? AND deleted_at IS NULL",
                (document_id, session.id),
            ).fetchone()
            if owned is None:
                raise ApiError(404, "document_not_found", "The document was not found.")
            raise ApiError(409, "revision_conflict", "The document changed; reload and retry.", True)
    return get_document(document_id, request, session)


@router.delete("/documents/{document_id}", status_code=204)
def delete_document(
    document_id: str,
    payload: DocumentDeleteRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> Response:
    now = datetime.now(UTC).isoformat()
    with request.app.state.database.transaction(immediate=True) as connection:
        cursor = connection.execute(
            """UPDATE documents SET deleted_at=?,updated_at=?,revision=revision+1
               WHERE id=? AND owner_session_id=? AND revision=? AND deleted_at IS NULL""",
            (now, now, document_id, session.id, payload.revision),
        )
        if cursor.rowcount != 1:
            owned = connection.execute(
                "SELECT 1 FROM documents WHERE id=? AND owner_session_id=? AND deleted_at IS NULL",
                (document_id, session.id),
            ).fetchone()
            if owned is None:
                raise ApiError(404, "document_not_found", "The document was not found.")
            raise ApiError(409, "revision_conflict", "The document changed; reload and retry.", True)
    return Response(status_code=204)


def _editor_rows(connection, owner: str, document_id: str):
    return connection.execute(
        """WITH latest_results AS (
             SELECT lr.*,ROW_NUMBER() OVER(
               PARTITION BY lr.recognition_run_id,lr.run_region_id ORDER BY lr.line_attempt DESC
             ) rank
             FROM recognition_line_results lr
           )
           SELECT p.id page_id,rr.source_region_id,rr.reading_order,rr.polygon_json,
                  lr.raw_text,c.id crop_id
           FROM pages p
           JOIN recognition_jobs j ON j.page_id=p.id AND j.id=(
             SELECT j2.id FROM recognition_jobs j2
             WHERE j2.page_id=p.id AND j2.owner_session_id=? AND j2.state IN ('completed','partial')
             ORDER BY j2.updated_at DESC,j2.created_at DESC LIMIT 1
           )
           JOIN recognition_runs r ON r.job_id=j.id AND r.attempt=(
             SELECT MAX(r2.attempt) FROM recognition_runs r2 WHERE r2.job_id=j.id
           )
           JOIN recognition_run_regions rr ON rr.recognition_run_id=r.id
           JOIN latest_results lr ON lr.recognition_run_id=r.id AND lr.run_region_id=rr.id
                                 AND lr.rank=1 AND lr.state='completed'
           JOIN recognition_line_crops c ON c.id=lr.crop_id AND c.owner_session_id=?
           WHERE p.document_id=?
           ORDER BY p.page_index,rr.reading_order""",
        (owner, owner, document_id),
    ).fetchall()


def _materialize_editor_lines(connection, owner: str, rows) -> list[EditorLineResponse]:
    now = datetime.now(UTC).isoformat()
    result: list[EditorLineResponse] = []
    for index, row in enumerate(rows):
        line = connection.execute(
            "SELECT id FROM text_lines WHERE region_id=? AND line_index=0",
            (row["source_region_id"],),
        ).fetchone()
        line_id = str(line["id"]) if line else str(uuid4())
        if line is None:
            connection.execute(
                """INSERT INTO text_lines(id,region_id,line_index,bbox_json,created_at,updated_at)
                   VALUES (?,?,?,?,?,?)""",
                (line_id, row["source_region_id"], 0, row["polygon_json"], now, now),
            )
        raw_text = str(row["raw_text"] or "")
        latest_raw = connection.execute(
            """SELECT text FROM text_versions WHERE line_id=? AND kind='raw'
               ORDER BY revision DESC LIMIT 1""",
            (line_id,),
        ).fetchone()
        max_revision = int(
            connection.execute(
                "SELECT COALESCE(MAX(revision),0) FROM text_versions WHERE line_id=?", (line_id,)
            ).fetchone()[0]
        )
        if latest_raw is None or latest_raw["text"] != raw_text:
            max_revision += 1
            connection.execute(
                """INSERT INTO text_versions(id,line_id,kind,text,revision,created_at,created_by_session_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (str(uuid4()), line_id, "raw", raw_text, max_revision, now, owner),
            )
        draft = connection.execute(
            "SELECT text,revision FROM editor_line_drafts WHERE line_id=? AND owner_session_id=?",
            (line_id, owner),
        ).fetchone()
        confirmed = connection.execute(
            """SELECT text,revision FROM text_versions WHERE line_id=? AND kind='confirmed'
               ORDER BY revision DESC LIMIT 1""",
            (line_id,),
        ).fetchone()
        effective_revision = max(
            max_revision,
            int(draft["revision"]) if draft else 0,
            int(confirmed["revision"]) if confirmed else 0,
        )
        text = draft["text"] if draft else (confirmed["text"] if confirmed else raw_text)
        status = "edited" if draft else ("confirmed" if confirmed else "unverified")
        result.append(
            EditorLineResponse(
                id=line_id,
                page_id=row["page_id"],
                position=index,
                raw_text=raw_text,
                text=str(text),
                status=status,
                revision=effective_revision,
                crop_url=f"/api/v1/line-crops/{row['crop_id']}/preview",
            )
        )
    return result


@router.get("/documents/{document_id}/editor", response_model=EditorDocumentResponse)
def get_document_editor(
    document_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> EditorDocumentResponse:
    document = get_document(document_id, request, session)
    with request.app.state.database.transaction(immediate=True) as connection:
        lines = _materialize_editor_lines(
            connection, session.id, _editor_rows(connection, session.id, document_id)
        )
    return EditorDocumentResponse(document=document, lines=lines)


def _owned_line(connection, owner: str, line_id: str):
    return connection.execute(
        """SELECT tl.id FROM text_lines tl
           JOIN recognition_regions rg ON rg.id=tl.region_id
           JOIN pages p ON p.id=rg.page_id
           JOIN documents d ON d.id=p.document_id
           WHERE tl.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
        (line_id, owner),
    ).fetchone()


def _line_revision(connection, owner: str, line_id: str) -> int:
    if _owned_line(connection, owner, line_id) is None:
        raise ApiError(404, "text_line_not_found", "The text line was not found.")
    version = int(
        connection.execute(
            "SELECT COALESCE(MAX(revision),0) FROM text_versions WHERE line_id=?", (line_id,)
        ).fetchone()[0]
    )
    draft = connection.execute(
        "SELECT revision FROM editor_line_drafts WHERE line_id=? AND owner_session_id=?",
        (line_id, owner),
    ).fetchone()
    return max(version, int(draft["revision"]) if draft else 0)


@router.put("/text-lines/{line_id}/draft", response_model=dict)
def save_line_draft(
    line_id: str,
    payload: EditorDraftRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    with request.app.state.database.transaction(immediate=True) as connection:
        current = _line_revision(connection, session.id, line_id)
        if current != payload.revision:
            raise ApiError(409, "revision_conflict", "The line changed; reload and retry.", True)
        revision = current + 1
        connection.execute(
            """INSERT INTO editor_line_drafts(line_id,owner_session_id,text,revision,updated_at)
               VALUES (?,?,?,?,?)
               ON CONFLICT(line_id) DO UPDATE SET text=excluded.text,revision=excluded.revision,
                 updated_at=excluded.updated_at WHERE owner_session_id=excluded.owner_session_id""",
            (line_id, session.id, payload.text, revision, now),
        )
    return {"line_id": line_id, "text": payload.text, "revision": revision, "updated_at": now}


@router.post("/text-lines/{line_id}/confirm", response_model=dict)
def confirm_line(
    line_id: str,
    payload: EditorConfirmRequest,
    request: Request,
    session: AuthenticatedSession = Depends(require_mutation_session),
) -> dict[str, object]:
    now = datetime.now(UTC).isoformat()
    with request.app.state.database.transaction(immediate=True) as connection:
        duplicate = connection.execute(
            """SELECT revision FROM editor_confirmation_idempotency
               WHERE owner_session_id=? AND idempotency_key=? AND line_id=?""",
            (session.id, payload.idempotency_key, line_id),
        ).fetchone()
        if duplicate:
            return {"line_id": line_id, "text": payload.text, "revision": int(duplicate["revision"]), "status": "confirmed"}
        current = _line_revision(connection, session.id, line_id)
        if current != payload.revision:
            raise ApiError(409, "revision_conflict", "The line changed; reload and retry.", True)
        source = connection.execute(
            "SELECT id FROM text_versions WHERE line_id=? ORDER BY revision DESC LIMIT 1", (line_id,)
        ).fetchone()
        next_revision = current + 1
        draft = connection.execute(
            "SELECT text FROM editor_line_drafts WHERE line_id=? AND owner_session_id=?",
            (line_id, session.id),
        ).fetchone()
        if draft:
            suggested_id = str(uuid4())
            connection.execute(
                """INSERT INTO text_versions(id,line_id,kind,text,revision,created_at,created_by_session_id)
                   VALUES (?,?,?,?,?,?,?)""",
                (suggested_id, line_id, "suggested", draft["text"], next_revision, now, session.id),
            )
            source = {"id": suggested_id}
            next_revision += 1
        confirmed_id = str(uuid4())
        connection.execute(
            """INSERT INTO text_versions(id,line_id,kind,text,revision,created_at,created_by_session_id)
               VALUES (?,?,?,?,?,?,?)""",
            (confirmed_id, line_id, "confirmed", payload.text, next_revision, now, session.id),
        )
        if source:
            connection.execute(
                """INSERT INTO corrections(id,line_id,from_version_id,to_version_id,owner_session_id,created_at)
                   VALUES (?,?,?,?,?,?)""",
                (str(uuid4()), line_id, source["id"], confirmed_id, session.id, now),
            )
        connection.execute(
            "DELETE FROM editor_line_drafts WHERE line_id=? AND owner_session_id=?",
            (line_id, session.id),
        )
        connection.execute(
            """INSERT INTO editor_confirmation_idempotency(
                 owner_session_id,idempotency_key,line_id,revision,created_at
               ) VALUES (?,?,?,?,?)""",
            (session.id, payload.idempotency_key, line_id, next_revision, now),
        )
    return {"line_id": line_id, "text": payload.text, "revision": next_revision, "status": "confirmed"}


@router.get("/line-crops/{crop_id}/preview")
def preview_line_crop(
    crop_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> Response:
    with request.app.state.database.connect() as connection:
        crop = connection.execute(
            """SELECT storage_key,sha256 FROM recognition_line_crops
               WHERE id=? AND owner_session_id=?""",
            (crop_id, session.id),
        ).fetchone()
    if crop is None:
        raise ApiError(404, "line_crop_not_found", "The line image was not found.")
    try:
        content = request.app.state.storage.resolve(crop["storage_key"]).read_bytes()
    except (OSError, ValueError) as error:
        raise ApiError(404, "line_crop_not_found", "The line image was not found.") from error
    return Response(
        content,
        media_type="image/png",
        headers={
            "Cache-Control": "private, max-age=300",
            "ETag": f'"{crop["sha256"][:24]}"',
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.post("/documents/upload", response_model=UploadResponse, status_code=201)
async def upload_document_file(
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> UploadResponse:
    content = await request.body()
    if not content:
        raise ApiError(422, "upload_empty", "The uploaded file is empty.")

    settings = request.app.state.settings
    if len(content) > settings.upload_max_bytes:
        raise ApiError(413, "upload_too_large", "The file exceeds the upload byte limit.")

    now = datetime.now(UTC).isoformat()
    document_id, page_id, asset_id = str(uuid4()), str(uuid4()), str(uuid4())
    storage_key = f"{session.id[:8]}/{asset_id}.png"

    # Validate image
    try:
        pil_img = Image.open(io.BytesIO(content))
        pil_img = ImageOps.exif_transpose(pil_img)
        width, height = pil_img.width, pil_img.height
        media_type = request.headers.get("content-type") or "image/png"
    except Exception as e:
        raise ApiError(422, "invalid_image", "Failed to parse uploaded image.") from e

    # Save to storage (Supabase or local)
    storage = request.app.state.storage
    if hasattr(storage, "upload"):
        storage.upload(storage_key, content, content_type=media_type)
    else:
        dest = storage.resolve(storage_key, temporary=False)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)

    filename = _safe_filename(request.headers.get("X-Original-Filename")) or "Manuscript.png"
    title = PurePath(filename).stem[:160]

    with request.app.state.database.transaction(immediate=True) as connection:
        connection.execute(
            "INSERT INTO documents(id,owner_session_id,title,status,created_at,updated_at) VALUES (?,?,?,?,?,?)",
            (document_id, session.id, title, "draft", now, now)
        )
        connection.execute(
            """INSERT INTO assets(id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,original_filename,kind,width,height)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (asset_id, session.id, document_id, storage_key, hashlib.sha256(content).hexdigest(), len(content), media_type, "committed", now, filename, "original", width, height)
        )
        connection.execute(
            "INSERT INTO pages(id,document_id,source_asset_id,page_index,created_at,updated_at) VALUES (?,?,?,0,?,?)",
            (page_id, document_id, asset_id, now, now)
        )

    return UploadResponse(
        document_id=document_id,
        page_id=page_id,
        asset=AssetResponse(
            id=asset_id,
            media_type=media_type,
            width=width,
            height=height,
            preview_url=f"/api/v1/assets/{asset_id}/preview",
        ),
    )


class SynchronousRecognitionResponse(BaseModel):
    document_id: str
    page_id: str
    raw_text: str
    lines: list[dict[str, Any]]


@router.post("/documents/{document_id}/pages/{page_id}/recognize", response_model=SynchronousRecognitionResponse)
def recognize_document_page(
    document_id: str,
    page_id: str,
    request: Request,
    session: AuthenticatedSession = Depends(require_session),
) -> SynchronousRecognitionResponse:
    settings = request.app.state.settings
    if not settings.openrouter_api_key:
        raise ApiError(500, "ocr_not_configured", "OPENROUTER_API_KEY is not configured.")

    # 1. Fetch page and asset
    with request.app.state.database.connect() as conn:
        row = conn.execute(
            """SELECT p.id as page_id, p.document_id,
                      COALESCE(p.prepared_asset_id, p.source_asset_id) as active_asset_id
               FROM pages p
               JOIN documents d ON d.id = p.document_id
               WHERE p.id = ? AND p.document_id = ? AND d.owner_session_id = ?""",
            (page_id, document_id, session.id)
        ).fetchone()

        if not row:
            # Fallback check by document_id alone
            row = conn.execute(
                """SELECT p.id as page_id, p.document_id,
                          COALESCE(p.prepared_asset_id, p.source_asset_id) as active_asset_id
                   FROM pages p
                   JOIN documents d ON d.id = p.document_id
                   WHERE p.document_id = ? AND d.owner_session_id = ?
                   ORDER BY p.page_index ASC LIMIT 1""",
                (document_id, session.id)
            ).fetchone()

        if not row:
            raise ApiError(404, "page_not_found", "Document or page was not found.")

        asset_id = row["active_asset_id"]
        actual_page_id = row["page_id"]

        asset_row = conn.execute(
            "SELECT storage_key FROM assets WHERE id = ?",
            (asset_id,)
        ).fetchone()
        if not asset_row:
            raise ApiError(404, "asset_not_found", "Asset file was not found.")

    storage_key = asset_row["storage_key"]
    storage = request.app.state.storage
    try:
        if hasattr(storage, "download"):
            data = storage.download(storage_key)
        else:
            data = storage.resolve(storage_key).read_bytes()
        pil_image = Image.open(io.BytesIO(data))
        pil_image = ImageOps.exif_transpose(pil_image).convert("RGB")
    except Exception as e:
        raise ApiError(422, "image_read_failed", f"Failed to load image: {e}")

    # 2. Run OCR directly using OpenRouter / Gemini
    runtime = GeminiOcrRuntime(
        api_key=settings.openrouter_api_key,
        model=settings.ocr_model,
        timeout_seconds=settings.ocr_timeout_seconds,
        thinking_level=settings.ocr_thinking_level,
        max_output_tokens=settings.ocr_max_output_tokens,
        max_page_regions=settings.ocr_max_page_regions,
    )

    try:
        detection = runtime.detect_page(pil_image)
    except Exception as e:
        logger.exception("OCR recognition error: %s", e)
        raise ApiError(502, "ocr_failed", f"AI recognition service error: {e}")

    # 3. Save results to database
    raw_lines = []
    lines_output = []
    now = datetime.now(UTC).isoformat()
    job_id = str(uuid4())
    run_id = str(uuid4())

    with request.app.state.database.transaction(immediate=True) as conn:
        conn.execute(
            """INSERT INTO recognition_jobs (id, owner_session_id, document_id, state, revision, created_at, updated_at, started_at, finished_at)
               VALUES (?, ?, ?, 'completed', 1, ?, ?, ?, ?)""",
            (job_id, session.id, document_id, now, now, now, now)
        )
        conn.execute(
            """INSERT INTO recognition_runs (id, job_id, attempt, started_at, finished_at, outcome)
               VALUES (?, ?, 1, ?, ?, 'succeeded')""",
            (run_id, job_id, now, now)
        )

        for i, region in enumerate(detection.regions):
            region_id = str(uuid4())
            line_id = str(uuid4())
            text = region.text.strip()
            raw_lines.append(text)
            lines_output.append({"id": line_id, "position": i + 1, "text": text})

            box_json = json.dumps(list(region.box_2d))
            conn.execute(
                """INSERT OR REPLACE INTO recognition_regions (id, page_id, polygon_json, reading_order, revision, created_at, updated_at)
                   VALUES (?, ?, ?, ?, 1, ?, ?)""",
                (region_id, actual_page_id, box_json, i + 1, now, now)
            )
            conn.execute(
                """INSERT OR REPLACE INTO text_lines (id, region_id, line_index, bbox_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (line_id, region_id, i + 1, box_json, now, now)
            )
            conn.execute(
                """INSERT OR REPLACE INTO text_versions (id, line_id, kind, text, revision, created_at, created_by_session_id)
                   VALUES (?, ?, 'raw', ?, 1, ?, ?)""",
                (str(uuid4()), line_id, text, now, session.id)
            )
            conn.execute(
                """INSERT OR REPLACE INTO text_versions (id, line_id, kind, text, revision, created_at, created_by_session_id)
                   VALUES (?, ?, 'confirmed', ?, 1, ?, ?)""",
                (str(uuid4()), line_id, text, now, session.id)
            )

        full_raw_text = "\n".join(raw_lines)

        conn.execute(
            """INSERT INTO page_raw_results (id, recognition_run_id, page_id, owner_session_id, raw_text, is_partial, created_at)
               VALUES (?, ?, ?, ?, ?, 0, ?)""",
            (str(uuid4()), run_id, actual_page_id, session.id, full_raw_text, now)
        )

        conn.execute(
            "UPDATE documents SET status = 'ready', updated_at = ? WHERE id = ?",
            (now, document_id)
        )

    return SynchronousRecognitionResponse(
        document_id=document_id,
        page_id=actual_page_id,
        raw_text=full_raw_text,
        lines=lines_output,
    )

