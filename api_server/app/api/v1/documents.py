from __future__ import annotations

import io
import json
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import PurePath
from urllib.parse import unquote
from uuid import uuid4

from fastapi import APIRouter, Depends, Header, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from PIL import Image, ImageOps

from app.api.dependencies import AuthenticatedSession, require_mutation_session, require_session
from app.core.errors import ApiError
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
            connection.execute("UPDATE pages SET prepared_asset_id=?,preprocessing_recipe_hash=?,revision=revision+1,updated_at=? WHERE id=?", (asset_id, digest, now, page_id))
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
