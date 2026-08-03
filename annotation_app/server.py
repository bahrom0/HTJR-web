from __future__ import annotations

import io
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps, UnidentifiedImageError
from pydantic import BaseModel, Field

from .database import AnnotationDatabase, IMAGE_EXTENSIONS
from .exporter import export_dataset


APP_ROOT = Path(__file__).resolve().parent
WORKSPACE_ROOT = APP_ROOT.parent
DATA_ROOT = Path(os.environ.get("KRAKEN_ANNOTATION_DATA", APP_ROOT / "data")).resolve()
UPLOAD_ROOT = DATA_ROOT / "uploads"
EXPORT_ROOT = DATA_ROOT / "exports"
RAW_DATASET = WORKSPACE_ROOT / "raw_dataset"
MAX_UPLOAD_BYTES = 50 * 1024 * 1024
database = AnnotationDatabase(DATA_ROOT / "annotations.sqlite3")


class RegionPayload(BaseModel):
    x: float
    y: float
    width: float = Field(gt=0)
    height: float = Field(gt=0)
    baseline_y: float
    baseline_angle: float = Field(default=0.0, ge=-20.0, le=20.0)
    line_type: str = "DefaultLine"


class AnnotationPayload(BaseModel):
    regions: list[RegionPayload]
    split: str = "unassigned"
    document_label: str = ""
    notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = None


@asynccontextmanager
async def lifespan(_: FastAPI):
    DATA_ROOT.mkdir(parents=True, exist_ok=True)
    UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)
    EXPORT_ROOT.mkdir(parents=True, exist_ok=True)
    database.initialize()
    yield


app = FastAPI(title="Kraken Annotator", version="0.1.0", lifespan=lifespan)


def _image_or_404(image_id: int) -> dict[str, Any]:
    image = database.get_image(image_id)
    if image is None:
        raise HTTPException(status_code=404, detail="image_not_found")
    return image


@app.get("/api/health")
def health() -> dict[str, object]:
    return {"status": "ok", "database": str(database.path)}


@app.get("/api/stats")
def stats() -> dict[str, int]:
    return database.stats()


@app.post("/api/import/raw-dataset")
def import_raw_dataset() -> dict[str, int]:
    if not RAW_DATASET.is_dir():
        raise HTTPException(status_code=404, detail="raw_dataset_not_found")
    return database.import_directory(RAW_DATASET)


@app.post("/api/import/file")
async def import_file(
    request: Request,
    filename: str = Query(min_length=1, max_length=255),
) -> dict[str, object]:
    suffix = Path(filename).suffix.lower()
    if suffix not in IMAGE_EXTENSIONS:
        raise HTTPException(status_code=415, detail="unsupported_image")
    payload = await request.body()
    if not payload or len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="invalid_upload_size")
    try:
        with Image.open(io.BytesIO(payload)) as image:
            ImageOps.exif_transpose(image).verify()
    except (UnidentifiedImageError, OSError):
        raise HTTPException(status_code=415, detail="invalid_image") from None
    safe_name = Path(filename).name
    destination = UPLOAD_ROOT / f"{os.urandom(8).hex()}_{safe_name}"
    destination.write_bytes(payload)
    try:
        image_id, created = database.import_path(destination)
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    if not created:
        destination.unlink(missing_ok=True)
    return {"id": image_id, "created": created}


@app.get("/api/images")
def list_images(
    status: str | None = None,
    search: str | None = None,
    limit: int = Query(default=500, ge=1, le=2000),
    offset: int = Query(default=0, ge=0),
) -> list[dict[str, Any]]:
    return database.list_images(status=status, search=search, limit=limit, offset=offset)


@app.get("/api/images/{image_id}")
def get_image(image_id: int) -> dict[str, Any]:
    return _image_or_404(image_id)


@app.get("/api/images/{image_id}/content")
def image_content(image_id: int) -> FileResponse:
    image = _image_or_404(image_id)
    path = Path(str(image["source_path"]))
    if not path.is_file():
        raise HTTPException(status_code=404, detail="image_file_missing")
    return FileResponse(
        path,
        filename=str(image["filename"]),
        content_disposition_type="inline",
        headers={"Cache-Control": "private, max-age=3600"},
    )


@app.put("/api/images/{image_id}/annotations")
@app.post("/api/images/{image_id}/annotations")
def save_annotations(image_id: int, payload: AnnotationPayload) -> dict[str, Any]:
    try:
        return database.save_annotations(
            image_id,
            regions=[region.model_dump() for region in payload.regions],
            split=payload.split,
            document_label=payload.document_label,
            notes=payload.notes,
            metadata=payload.metadata,
            expected_revision=payload.expected_revision,
        )
    except KeyError:
        raise HTTPException(status_code=404, detail="image_not_found") from None
    except RuntimeError as error:
        if str(error) == "revision_conflict":
            raise HTTPException(status_code=409, detail="revision_conflict") from None
        raise
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None


@app.post("/api/export")
def create_export() -> dict[str, object]:
    try:
        result = export_dataset(database, EXPORT_ROOT)
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from None
    result["download_url"] = f"/api/exports/{quote(str(result['export_id']))}.zip"
    return result


@app.get("/api/exports/{export_id}.zip")
def download_export(export_id: str) -> FileResponse:
    if not export_id.replace("-", "").replace("_", "").isalnum():
        raise HTTPException(status_code=400, detail="invalid_export_id")
    archive = EXPORT_ROOT / f"{export_id}.zip"
    if not archive.is_file():
        raise HTTPException(status_code=404, detail="export_not_found")
    return FileResponse(archive, filename=archive.name, media_type="application/zip")


@app.get("/app.js", include_in_schema=False)
def annotation_javascript() -> FileResponse:
    # Windows' system MIME registry can make mimetypes.guess_type(".js")
    # resolve to text/plain. Browsers reject that response for module scripts,
    # leaving the rendered annotator with no event handlers at all.
    return FileResponse(
        APP_ROOT / "static" / "app.js",
        media_type="application/javascript",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/styles.css", include_in_schema=False)
def annotation_stylesheet() -> FileResponse:
    return FileResponse(
        APP_ROOT / "static" / "styles.css",
        media_type="text/css",
        headers={"Cache-Control": "no-cache"},
    )


app.mount("/", StaticFiles(directory=APP_ROOT / "static", html=True), name="static")
