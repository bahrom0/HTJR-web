from __future__ import annotations

import io
import json
import re
from datetime import UTC, datetime
from uuid import uuid4

from fastapi import APIRouter, Request
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field, field_validator
from starlette.concurrency import run_in_threadpool

from app.core.errors import ApiError
from app.core.settings import settings
from app.ml.kraken_runtime import KrakenRuntime, KrakenRuntimeError


router = APIRouter(prefix="/demo", tags=["demo"])
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_IMAGE_TYPES = {"image/jpeg", "image/png", "image/webp"}


class DemoPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class DemoRegion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(min_length=1, max_length=100)
    polygon: list[DemoPoint]
    reading_order: int = Field(ge=0)
    text: str = Field(max_length=10_000)

    @field_validator("polygon")
    @classmethod
    def four_points(cls, value: list[DemoPoint]) -> list[DemoPoint]:
        if len(value) != 4:
            raise ValueError("region_polygon_invalid")
        return value


class DemoPresetInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    original_filename: str | None = Field(default=None, max_length=255)
    regions: list[DemoRegion] = Field(min_length=1, max_length=500)


class DemoPresetResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image_sha256: str
    text: str
    original_filename: str | None
    regions: list[DemoRegion]


class DemoDetectionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    detector_version: str
    regions: list[DemoRegion]


def _validate_sha256(value: str) -> str:
    normalized = value.lower()
    if not _SHA256.fullmatch(normalized):
        raise ApiError(422, "image_sha256_invalid", "The image SHA-256 is invalid.")
    return normalized


def _ordered_regions(regions: list[DemoRegion]) -> list[DemoRegion]:
    ordered = sorted(regions, key=lambda region: region.reading_order)
    if any(region.reading_order != index for index, region in enumerate(ordered)):
        raise ApiError(422, "demo_region_order_invalid", "Region reading order must be contiguous.")
    if any(not region.text.strip() for region in ordered):
        raise ApiError(422, "demo_region_text_empty", "Every region must have text.")
    return ordered


def _response(row) -> DemoPresetResponse:
    regions = [DemoRegion.model_validate(value) for value in json.loads(row["regions_json"])]
    return DemoPresetResponse(
        image_sha256=str(row["image_sha256"]), text=str(row["raw_text"]),
        original_filename=row["original_filename"], regions=regions,
    )


@router.get("/presets/{image_sha256}", response_model=DemoPresetResponse)
def get_demo_preset(image_sha256: str, request: Request) -> DemoPresetResponse:
    digest = _validate_sha256(image_sha256)
    with request.app.state.database.connect() as connection:
        row = connection.execute(
            "SELECT image_sha256,raw_text,original_filename,regions_json FROM demo_recognition_presets WHERE image_sha256=?",
            (digest,),
        ).fetchone()
    if row is None:
        raise ApiError(404, "demo_preset_not_found", "No preset exists for this image.")
    return _response(row)


@router.put("/presets/{image_sha256}", response_model=DemoPresetResponse)
def save_demo_preset(image_sha256: str, body: DemoPresetInput, request: Request) -> DemoPresetResponse:
    digest = _validate_sha256(image_sha256)
    regions = _ordered_regions(body.regions)
    raw_text = "\n".join(region.text.strip() for region in regions)
    regions_json = json.dumps([region.model_dump() for region in regions], ensure_ascii=False, separators=(",", ":"))
    now = datetime.now(UTC).isoformat()
    with request.app.state.database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO demo_recognition_presets(image_sha256,raw_text,original_filename,regions_json,created_at,updated_at)
               VALUES (?,?,?,?,?,?) ON CONFLICT(image_sha256) DO UPDATE SET
               raw_text=excluded.raw_text,original_filename=excluded.original_filename,
               regions_json=excluded.regions_json,updated_at=excluded.updated_at""",
            (digest, raw_text, body.original_filename, regions_json, now, now),
        )
        row = connection.execute(
            "SELECT image_sha256,raw_text,original_filename,regions_json FROM demo_recognition_presets WHERE image_sha256=?",
            (digest,),
        ).fetchone()
    return _response(row)


@router.post("/detect-regions", response_model=DemoDetectionResponse)
async def detect_demo_regions(request: Request) -> DemoDetectionResponse:
    media_type = request.headers.get("content-type", "").split(";", 1)[0].lower()
    if media_type not in _IMAGE_TYPES:
        raise ApiError(415, "unsupported_image_type", "Use a JPEG, PNG, or WebP image.")
    payload = await request.body()
    if not payload or len(payload) > settings.upload_max_bytes:
        raise ApiError(413, "upload_too_large", "The image exceeds the upload byte limit.")
    try:
        with Image.open(io.BytesIO(payload)) as source:
            source.load()
            image = source.convert("RGB")
    except (UnidentifiedImageError, OSError, ValueError) as error:
        raise ApiError(422, "image_decode_failed", "The image could not be decoded safely.") from error
    runtime = KrakenRuntime(settings.kraken_endpoint, timeout_seconds=settings.kraken_timeout_seconds)
    try:
        detection = await run_in_threadpool(runtime.detect, image)
    except KrakenRuntimeError as error:
        raise ApiError(503, str(error), "Kraken could not detect text lines.", retryable=True) from error
    finally:
        image.close()
    regions: list[DemoRegion] = []
    for line in detection.lines:
        xs = [point[0] / detection.width for point in line.boundary]
        ys = [point[1] / detection.height for point in line.boundary]
        left, right = max(0.0, min(xs)), min(1.0, max(xs))
        top, bottom = max(0.0, min(ys)), min(1.0, max(ys))
        regions.append(DemoRegion(
            id=str(uuid4()), reading_order=line.reading_order, text="",
            polygon=[DemoPoint(x=left, y=top), DemoPoint(x=right, y=top),
                     DemoPoint(x=right, y=bottom), DemoPoint(x=left, y=bottom)],
        ))
    return DemoDetectionResponse(detector_version=detection.detector_version, regions=regions)
