from __future__ import annotations

import argparse
import base64
import hashlib
import json
import logging
import signal
import subprocess
import sys
import threading
import time
import zlib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import numpy as np
from PIL import Image, ImageOps

from app.core.database import Database
from app.core.logging import configure_logging
from app.core.settings import settings
from app.core.storage import FileStorage
from app.ml.gemini_runtime import GeminiOcrRuntime, GeminiPageResult, GeminiRuntimeError

# Lightweight fallback stubs for cloud / Gemini-only execution
class CraftRuntimeError(RuntimeError): pass
class CraftRuntime: pass
class CraftDetection: pass
DEFAULT_THRESHOLDS: dict[str, float] = {}

class KrakenRuntimeError(RuntimeError): pass
class KrakenRuntime: pass
class KrakenDetection: pass

class TrocrRuntimeError(RuntimeError): pass
class TrocrRuntime: pass
class TrocrGeneration: pass

if settings.ocr_provider != "gemini":
    try:
        from app.ml.craft_runtime import DEFAULT_THRESHOLDS, CraftDetection, CraftRuntime, CraftRuntimeError
        from app.ml.kraken_runtime import KrakenDetection, KrakenRuntime, KrakenRuntimeError
        from app.ml.trocr_runtime import TrocrGeneration, TrocrRuntime, TrocrRuntimeError
    except ImportError:
        pass

from app.repositories.jobs import JobRepository, LostLease
from app.repositories.recognition import (
    RecognitionInputInvalid,
    RecognitionRepository,
    RecognitionRunNotFound,
    RunRegion,
    StoredCrop,
    assess_line_crop,
)
from app.repositories.regions import RegionRepository, RegionRevisionConflict
from app.services.jobs import JobCancelled, JobContext, JobResult, RetryableJobError, TerminalJobError, WorkerService
from app.services.regions import (
    BoundingBox,
    DetectorComponent,
    GroupingParameters,
    LineCandidate,
    LineReconstructionParameters,
    group_components,
    grouping_metrics,
    reading_order,
    reconstruct_line_regions,
)


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _sha256(path: Path) -> str | None:
    if not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _pipeline_manifest_sha256(
    models_root: Path,
    *,
    detector_name: str,
    detector_model_sha256: str | None = None,
) -> str | None:
    """Hash only local, versioned model manifests; never inspect image content."""
    entries = {
        "detector": (
            _sha256(models_root / "craft" / "manifest.json")
            if detector_name == "craft"
            else detector_model_sha256
        ),
        "trocr": _sha256(models_root / "manifest.json"),
    }
    if not all(entries.values()):
        return None
    return hashlib.sha256(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _encoded_map(score_map: object) -> dict[str, object]:
    array = score_map  # numpy float32 score map, not exposed to HTTP callers.
    raw = array.astype("float32", copy=False).tobytes()
    return {
        "shape": list(array.shape),
        "dtype": "float32",
        "zlib_base64": base64.b64encode(zlib.compress(raw, 6)).decode("ascii"),
    }


def _rectangle(box: BoundingBox) -> list[dict[str, float]]:
    return [
        {"x": round(box.left, 8), "y": round(box.top, 8)},
        {"x": round(box.right, 8), "y": round(box.top, 8)},
        {"x": round(box.right, 8), "y": round(box.bottom, 8)},
        {"x": round(box.left, 8), "y": round(box.bottom, 8)},
    ]


def _normalised_component(index: int, box: tuple[float, float, float, float], score: float, *, width: int, height: int) -> DetectorComponent | None:
    left, top, right, bottom = box
    normalized = BoundingBox(
        max(0.0, min(1.0, left / width)),
        max(0.0, min(1.0, top / height)),
        max(0.0, min(1.0, right / width)),
        max(0.0, min(1.0, bottom / height)),
    )
    return DetectorComponent(f"craft_component_{index}", normalized, max(0.0, min(1.0, score)))


def _normalised_kraken_quad(
    boundary: tuple[tuple[float, float], ...],
    *,
    width: int,
    height: int,
) -> list[dict[str, float]]:
    """Convert Kraken's detailed boundary into the review UI's four-point contract."""
    points = np.asarray(boundary, dtype=np.float32)
    if points.ndim != 2 or points.shape[0] < 3 or points.shape[1] != 2:
        raise ValueError("kraken_boundary_invalid")
    import cv2
    rectangle = cv2.minAreaRect(points)
    quad = cv2.boxPoints(rectangle)
    center = quad.mean(axis=0)
    angles = np.arctan2(quad[:, 1] - center[1], quad[:, 0] - center[0])
    ordered = quad[np.argsort(angles)]
    polygon = [
        {
            "x": round(max(0.0, min(1.0, float(x) / width)), 8),
            "y": round(max(0.0, min(1.0, float(y) / height)), 8),
        }
        for x, y in ordered
    ]
    area = sum(
        point["x"] * polygon[(index + 1) % 4]["y"]
        - polygon[(index + 1) % 4]["x"] * point["y"]
        for index, point in enumerate(polygon)
    )
    if abs(area) < 0.000001:
        raise ValueError("kraken_boundary_invalid")
    return polygon


def _load_prepared_page(context: JobContext, database: Database) -> tuple[int, str, str, str, str]:
    with database.connect() as connection:
        page = connection.execute(
            """SELECT p.revision,p.prepared_asset_id,a.sha256,a.storage_key,p.document_id
               FROM pages p
               JOIN assets a ON a.id=p.prepared_asset_id AND a.state='committed'
               WHERE p.id=? AND p.document_id=?""",
            (context.job.page_id, context.job.document_id),
        ).fetchone()
    if page is None:
        raise TerminalJobError("craft_prepared_page_missing")
    return (
        int(page["revision"]),
        str(page["prepared_asset_id"]),
        str(page["sha256"]),
        str(page["storage_key"]),
        str(page["document_id"]),
    )


def _demo_preset_regions(context: JobContext, database: Database) -> list[dict[str, object]] | None:
    with database.connect() as connection:
        row = connection.execute(
            """SELECT dp.regions_json FROM pages p
               JOIN assets a ON a.id=p.source_asset_id AND a.state='committed'
               JOIN demo_recognition_presets dp ON dp.image_sha256=a.sha256
               WHERE p.id=? AND p.document_id=?""",
            (context.job.page_id, context.job.document_id),
        ).fetchone()
    if row is None:
        return None
    value = json.loads(row["regions_json"])
    return value if isinstance(value, list) and value else None


def _apply_demo_regions(context: JobContext, database: Database) -> bool:
    preset = _demo_preset_regions(context, database)
    if preset is None:
        return False
    page_revision, prepared_asset_id, prepared_sha256, _storage_key, _ = _load_prepared_page(context, database)
    regions = [
        {
            "id": str(uuid4()), "polygon": item["polygon"], "reading_order": index,
            "source": "kraken", "flags": ["demo_preset"],
            "detector_version": "kraken:demo-preset", "detector_score": None,
        }
        for index, item in enumerate(preset)
    ]
    try:
        persisted_revision = RegionRepository(database).replace(
            context.job.owner_session_id, context.job.page_id, page_revision, regions,
        )
    except RegionRevisionConflict as error:
        raise RetryableJobError("demo_region_revision_conflict") from error
    context.repository.set_run_metadata(
        context.job.id, context.worker_id, prepared_asset_id=prepared_asset_id,
        prepared_asset_sha256=prepared_sha256, page_revision=persisted_revision,
        detector_name="kraken", detector_version="kraken:demo-preset",
        detector_config_json='{"source":"demo_preset"}',
    )
    time.sleep(1.2)
    context.complete_stage("detecting_regions", processed_count=1, total_count=1)
    logging.getLogger(__name__).info("demo_regions_loaded job_id=%s count=%s", context.job.id, len(regions))
    return True


def _recognize_demo_preset(context: JobContext, database: Database, storage: FileStorage) -> bool:
    preset = _demo_preset_regions(context, database)
    if preset is None:
        return False
    repository = RecognitionRepository(database, storage)
    run_id = context.repository.active_run_id(context.job.id)
    regions = repository.run_regions(context.job.owner_session_id, run_id)
    if len(regions) != len(preset):
        raise TerminalJobError("demo_region_count_mismatch")
    try:
        with Image.open(storage.resolve(repository.prepared_storage_key(context.job.owner_session_id, run_id))) as source:
            prepared_image = source.convert("RGB")
    except OSError as error:
        raise TerminalJobError("recognition_prepared_page_decode_failed") from error
    results = repository.latest_results(context.job.owner_session_id, run_id)
    processed = sum(result.state == "completed" for result in results.values())
    total = len(regions)
    delay = max(0.3, min(1.1, 7.0 / max(total, 1)))
    time.sleep(1.0)
    try:
        for region in regions:
            if results.get(region.id) is not None and results[region.id].state == "completed":
                continue
            item = preset[region.reading_order]
            crop = repository.crop_for_region(
                context.job.owner_session_id, run_id, region, prepared_image,
                padding_fraction=settings.line_crop_padding,
            )
            repository.record_success(
                context.job.owner_session_id, run_id, region, crop,
                raw_text=str(item["text"]).strip(),
                generation={"source": "demo_preset", "reading_order": region.reading_order},
                duration_ms=int(delay * 1000),
            )
            processed += 1
            context.advance_progress("recognizing_lines", processed_count=processed, total_count=total)
            time.sleep(delay)
    finally:
        prepared_image.close()
    context.complete_stage("recognizing_lines", processed_count=processed, total_count=total)
    repository.assemble_raw_page(context.job.owner_session_id, run_id)
    context.complete_stage("assembling", processed_count=processed, total_count=total)
    context.complete_stage("ready_for_review", processed_count=processed, total_count=total)
    logging.getLogger(__name__).info("demo_lines_completed job_id=%s count=%s", context.job.id, total)
    return True


def _detect_regions(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    models_root: Path,
    runtime: CraftRuntime | KrakenRuntime | GeminiOcrRuntime,
) -> JobResult:
    context.checkpoint()
    page_revision, prepared_asset_id, prepared_sha256, storage_key, _ = _load_prepared_page(context, database)
    try:
        with Image.open(storage.resolve(storage_key)) as source:
            result = runtime.detect(source)
    except (CraftRuntimeError, KrakenRuntimeError, GeminiRuntimeError) as error:
        logging.getLogger(__name__).exception(
            "detector_request_failed detector=%s code=%s",
            type(runtime).__name__,
            str(error),
        )
        raise RetryableJobError(str(error)) from error
    except OSError as error:
        raise TerminalJobError("detector_page_decode_failed") from error
    context.checkpoint()

    if isinstance(result, GeminiPageResult):
        detector_name = "gemini_openrouter"
        source_regions = []
        raw_lines = []
        for region in result.regions:
            top, left, bottom, right = region.box_2d
            polygon = [
                {"x": left / 1000, "y": top / 1000},
                {"x": right / 1000, "y": top / 1000},
                {"x": right / 1000, "y": bottom / 1000},
                {"x": left / 1000, "y": bottom / 1000},
            ]
            source_regions.append(
                {
                    "id": f"gemini:{region.reading_order}",
                    "polygon": polygon,
                    "reading_order": region.reading_order,
                    "source": "gemini_openrouter",
                    "flags": ["gemini_page_detection", "normalized_box_0_1000"],
                    "detector_version": result.detector_version,
                    "detector_score": None,
                }
            )
            raw_lines.append(
                {
                    "reading_order": region.reading_order,
                    "box_2d": list(region.box_2d),
                    "draft_text": region.text,
                }
            )
        regions, line_reconstruction = reconstruct_line_regions(
            source_regions,
            LineReconstructionParameters(page_aspect_ratio=result.image_width / result.image_height),
        )
        detector_model_sha256 = None
        detector_config = {
            "schema_version": 1,
            "provider": "openrouter",
            "selected_provider": result.usage.provider,
            "model": result.detector_version,
            "thinking_level": settings.gemini_thinking_level,
            "max_page_regions": settings.gemini_max_page_regions,
            "usage": asdict(result.usage),
        }
        raw_output = {
            "image_size": [result.image_width, result.image_height],
            "duration_ms": result.duration_ms,
            "lines": raw_lines,
            "source_region_count": len(source_regions),
            "region_count": len(regions),
            "line_reconstruction": line_reconstruction,
        }
    elif isinstance(result, KrakenDetection):
        detector_name = "kraken"
        source_regions: list[dict[str, object]] = []
        raw_lines = []
        for line in result.lines:
            try:
                polygon = _normalised_kraken_quad(line.boundary, width=result.width, height=result.height)
            except ValueError:
                continue
            flags = ["kraken_blla", "boundary_min_area_quad"]
            if not line.baseline:
                flags.append("baseline_missing")
            source_regions.append(
                {
                    "id": f"kraken:{line.id}",
                    "polygon": polygon,
                    "reading_order": line.reading_order,
                    "source": "kraken",
                    "flags": flags,
                    "detector_version": result.detector_version,
                    "detector_score": None,
                    "baseline": [
                        {"x": x / result.width, "y": y / result.height}
                        for x, y in line.baseline
                    ],
                }
            )
            raw_lines.append(
                {
                    "id": line.id,
                    "reading_order": line.reading_order,
                    "boundary": [list(point) for point in line.boundary],
                    "baseline": [list(point) for point in line.baseline],
                }
            )
        regions, line_reconstruction = reconstruct_line_regions(
            source_regions,
            LineReconstructionParameters(page_aspect_ratio=result.width / result.height),
        )
        evidence = runtime.evidence
        detector_model_sha256 = evidence.model_sha256 if evidence is not None else None
        detector_config = {
            "schema_version": 1,
            "device": evidence.device if evidence is not None else None,
            "precision": evidence.dtype if evidence is not None else None,
            "model_sha256": detector_model_sha256,
        }
        raw_output: dict[str, object] = {
            "image_size": [result.width, result.height],
            "duration_ms": result.duration_ms,
            "warmup_ms": result.warmup_ms,
            "lines": raw_lines,
            "source_region_count": len(source_regions),
            "region_count": len(regions),
            "line_reconstruction": line_reconstruction,
        }
    else:
        detector_name = "craft"
        assert isinstance(result, CraftDetection)
        components: list[DetectorComponent] = []
        for index, (box, score) in enumerate(zip(result.boxes, result.scores, strict=True)):
            try:
                component = _normalised_component(index, box, score, width=result.width, height=result.height)
            except ValueError:
                component = None
            if component is not None:
                components.append(component)
        grouping = GroupingParameters()
        line_candidates = reading_order(group_components(components, grouping), grouping)
        single_line_full_width = len(line_candidates) == 1 and line_candidates[0].bbox.width < 0.9
        if single_line_full_width:
            candidate = line_candidates[0]
            line_candidates = [
                LineCandidate(
                    BoundingBox(0.0, candidate.bbox.top, 1.0, candidate.bbox.bottom),
                    candidate.component_ids,
                    candidate.score,
                    tuple(dict.fromkeys((*candidate.flags, "single_line_full_width"))),
                )
            ]
        if single_line_full_width:
            source_regions = [
                {
                    "id": "craft:single-line",
                    "polygon": _rectangle(line_candidates[0].bbox),
                    "source": "craft",
                    "flags": list(line_candidates[0].flags),
                    "detector_version": result.detector_version,
                    "detector_score": line_candidates[0].score,
                }
            ]
        else:
            source_regions = [
                {
                    "id": component.id,
                    "polygon": _rectangle(component.bbox),
                    "source": "craft",
                    "flags": [],
                    "detector_version": result.detector_version,
                    "detector_score": component.score,
                }
                for component in components
            ]
        regions, line_reconstruction = reconstruct_line_regions(
            source_regions,
            LineReconstructionParameters(page_aspect_ratio=result.width / result.height),
        )
        detector_model_sha256 = None
        detector_config = {"version": result.thresholds_version, "values": DEFAULT_THRESHOLDS}
        raw_output = {
            "image_size": [result.width, result.height],
            "duration_ms": result.duration_ms,
            "warmup_ms": result.warmup_ms,
            "text_score_map": _encoded_map(result.text_score_map),
            "link_score_map": _encoded_map(result.link_score_map),
            "boxes": [list(box) for box in result.boxes],
            "polygons": [[list(point) for point in polygon] for polygon in result.polygons],
            "scores": list(result.scores),
            "grouping": {
                "parameters": asdict(grouping),
                "component_count": len(components),
                "line_candidate_count": len(line_candidates),
                "reconstruction_source_region_count": len(source_regions),
                "metrics": grouping_metrics(line_candidates),
                "lines": [
                    {
                        "component_ids": list(candidate.component_ids),
                        "bbox": [candidate.bbox.left, candidate.bbox.top, candidate.bbox.right, candidate.bbox.bottom],
                        "flags": list(candidate.flags),
                        "score": candidate.score,
                    }
                    for candidate in line_candidates
                ],
            },
            "line_reconstruction": line_reconstruction,
        }
    try:
        persisted_page_revision = RegionRepository(database).replace(
            context.job.owner_session_id,
            context.job.page_id,
            page_revision,
            regions,
        )
    except RegionRevisionConflict as error:
        raise RetryableJobError("detector_region_revision_conflict") from error

    repository = context.repository
    run_id = repository.active_run_id(context.job.id)
    manifest_sha256 = _pipeline_manifest_sha256(
        models_root,
        detector_name=detector_name,
        detector_model_sha256=detector_model_sha256,
    )
    metadata: dict[str, object] = {
        "model_manifest_sha256": manifest_sha256,
        "pipeline_manifest_sha256": manifest_sha256,
        "prepared_asset_id": prepared_asset_id,
        "prepared_asset_sha256": prepared_sha256,
        "page_revision": persisted_page_revision,
        "detector_name": detector_name,
        "detector_version": result.detector_version,
        "detector_config_json": json.dumps(detector_config, sort_keys=True, separators=(",", ":")),
    }
    if detector_name == "craft":
        metadata["craft_detector_version"] = result.detector_version
        metadata["craft_thresholds_json"] = json.dumps(detector_config, sort_keys=True, separators=(",", ":"))
    repository.set_run_metadata(context.job.id, context.worker_id, **metadata)

    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO detector_outputs(
                   id,owner_session_id,page_id,job_id,recognition_run_id,detector_name,
                   detector_version,config_json,output_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                context.job.owner_session_id,
                context.job.page_id,
                context.job.id,
                run_id,
                detector_name,
                result.detector_version,
                json.dumps(detector_config, sort_keys=True, separators=(",", ":")),
                json.dumps(raw_output, separators=(",", ":")),
                _now(),
            ),
        )
        if detector_name == "craft":
            connection.execute(
                """INSERT INTO craft_detector_outputs(
                       id,owner_session_id,page_id,job_id,recognition_run_id,
                       detector_version,thresholds_json,output_json,created_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()),
                    context.job.owner_session_id,
                    context.job.page_id,
                    context.job.id,
                    run_id,
                    result.detector_version,
                    json.dumps(detector_config, sort_keys=True, separators=(",", ":")),
                    json.dumps(raw_output, separators=(",", ":")),
                    _now(),
                ),
            )
        connection.execute(
            """INSERT INTO line_reconstruction_audits(
                   id,owner_session_id,page_id,job_id,recognition_run_id,detector_name,
                   schema_version,parameters_json,source_regions_json,line_regions_json,merges_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                context.job.owner_session_id,
                context.job.page_id,
                context.job.id,
                run_id,
                detector_name,
                int(line_reconstruction["schema_version"]),
                json.dumps(line_reconstruction["parameters"], sort_keys=True, separators=(",", ":")),
                json.dumps(line_reconstruction["source_regions"], separators=(",", ":")),
                json.dumps(line_reconstruction["line_regions"], separators=(",", ":")),
                json.dumps(line_reconstruction["merges"], separators=(",", ":")),
                _now(),
            ),
        )
    context.complete_stage("detecting_regions", processed_count=1, total_count=1)
    return JobResult("awaiting_region_review")


_OCR_OBSERVATIONS = ("rectified_rgb", "rectified_grayscale_autocontrast")


def _line_generation_metadata(
    generation: object,
    *,
    num_beams: int,
    max_new_tokens: int,
    preprocessing: str | None = None,
    model_version: str | None = None,
    adapter_version: str | None = None,
) -> dict[str, object]:
    metadata: dict[str, object] = {
        "num_beams": num_beams,
        "max_new_tokens": max_new_tokens,
        "generated_token_count": generation.generated_token_count,
        "decoding_steps": generation.decoding_steps,
        "mean_token_log_probability": generation.mean_token_log_probability,
        "confidence": generation.mean_token_log_probability,
    }
    if preprocessing is not None:
        metadata["preprocessing"] = preprocessing
    if model_version is not None:
        metadata["model_version"] = model_version
    metadata["adapter_version"] = adapter_version
    return metadata


def _make_ocr_observation(image: Image.Image, profile: str) -> Image.Image:
    if profile == "rectified_rgb":
        return image.copy()
    if profile == "rectified_grayscale_autocontrast":
        grayscale = ImageOps.grayscale(image)
        # A one-percent tail cutoff is intentionally modest: it improves faded
        # pen strokes without introducing a thresholding/CLAHE branch.
        return ImageOps.autocontrast(grayscale, cutoff=1).convert("RGB")
    raise ValueError(f"unknown_ocr_observation:{profile}")


def _recognize_images(
    runtime: TrocrRuntime,
    images: list[Image.Image],
) -> tuple[TrocrGeneration, ...]:
    recognize_many = getattr(runtime, "recognize_many", None)
    if callable(recognize_many):
        return tuple(
            recognize_many(
                images,
                num_beams=settings.trocr_num_beams,
                max_new_tokens=settings.trocr_max_new_tokens,
            )
        )
    return tuple(
        runtime.recognize(
            image,
            num_beams=settings.trocr_num_beams,
            max_new_tokens=settings.trocr_max_new_tokens,
        )
        for image in images
    )


def _recognize_confirmed_lines(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    runtime: TrocrRuntime,
) -> JobResult:
    repository = RecognitionRepository(database, storage)
    run_id = context.repository.active_run_id(context.job.id)
    try:
        evidence = runtime.evidence or runtime.warmup()
    except TrocrRuntimeError as error:
        raise RetryableJobError(str(error)) from error
    generation_parameters = {
        "num_beams": settings.trocr_num_beams,
        "max_new_tokens": settings.trocr_max_new_tokens,
        "batch_size": settings.trocr_batch_size if evidence.device.startswith("cuda") else 1,
        "adapter_mode": settings.trocr_adapter_mode,
        "observation_profiles": list(_OCR_OBSERVATIONS),
    }
    context.repository.set_run_metadata(
        context.job.id,
        context.worker_id,
        model_manifest_sha256=evidence.manifest_sha256,
        pipeline_manifest_sha256=evidence.manifest_sha256,
        trocr_model_version=evidence.model_version,
        rslora_adapter_version=evidence.adapter_version,
        device=evidence.device,
        dtype=evidence.dtype,
        generation_parameters_json=json.dumps(generation_parameters, sort_keys=True, separators=(",", ":")),
    )
    prepared_image: Image.Image | None = None
    try:
        regions = repository.run_regions(context.job.owner_session_id, run_id)
        prepared_key = repository.prepared_storage_key(context.job.owner_session_id, run_id)
        with Image.open(storage.resolve(prepared_key)) as source:
            prepared_image = source.convert("RGB")
    except RecognitionRunNotFound as error:
        raise TerminalJobError("recognition_run_input_missing") from error
    except OSError as error:
        raise TerminalJobError("recognition_prepared_page_decode_failed") from error

    total = len(regions)
    results = repository.latest_results(context.job.owner_session_id, run_id)
    settled_states = {"completed", "failed_retryable", "failed_terminal"}
    processed = max(context.job.processed_count, sum(result.state in settled_states for result in results.values()))
    if processed > context.job.processed_count:
        context.advance_progress("recognizing_lines", processed_count=processed, total_count=total)

    batch_size = settings.trocr_batch_size if evidence.device.startswith("cuda") else 1
    pending_regions = [
        region
        for region in regions
        if (prior := results.get(region.id)) is None or prior.state not in {"completed", "failed_terminal"}
    ]
    try:
        for offset in range(0, len(pending_regions), batch_size):
            context.checkpoint()
            batch = pending_regions[offset:offset + batch_size]
            crops: list[tuple[RunRegion, StoredCrop]] = []
            profile_images: dict[str, list[Image.Image]] = {profile: [] for profile in _OCR_OBSERVATIONS}
            qualities: list[dict[str, object]] = []
            try:
                for region in batch:
                    crop = repository.crop_for_region(
                        context.job.owner_session_id,
                        run_id,
                        region,
                        prepared_image,
                        padding_fraction=settings.line_crop_padding,
                    )
                    crops.append((region, crop))
                    with Image.open(storage.resolve(crop.storage_key)) as crop_image:
                        rectified = crop_image.convert("RGB")
                    qualities.append(assess_line_crop(rectified))
                    for profile in _OCR_OBSERVATIONS:
                        profile_images[profile].append(_make_ocr_observation(rectified, profile))
                    rectified.close()

                generations_by_profile: dict[str, tuple[TrocrGeneration, ...]] = {}
                for profile in _OCR_OBSERVATIONS:
                    generations = _recognize_images(runtime, profile_images[profile])
                    if len(generations) != len(crops):
                        raise TrocrRuntimeError("trocr_batch_result_count_mismatch")
                    generations_by_profile[profile] = generations

                for index, ((region, crop), quality) in enumerate(zip(crops, qualities, strict=True)):
                    candidates: list[tuple[str, TrocrGeneration, dict[str, object]]] = []
                    for profile in _OCR_OBSERVATIONS:
                        generation = generations_by_profile[profile][index]
                        metadata = _line_generation_metadata(
                            generation,
                            num_beams=settings.trocr_num_beams,
                            max_new_tokens=settings.trocr_max_new_tokens,
                            preprocessing=profile,
                            model_version=evidence.model_version,
                            adapter_version=evidence.adapter_version,
                        )
                        metadata["text"] = generation.text
                        metadata["duration_ms"] = generation.duration_ms
                        candidates.append((profile, generation, metadata))
                    winner_profile, winner, winner_metadata = max(
                        candidates,
                        key=lambda item: (
                            item[1].mean_token_log_probability is not None,
                            item[1].mean_token_log_probability
                            if item[1].mean_token_log_probability is not None
                            else float("-inf"),
                            item[0] == "rectified_rgb",
                        ),
                    )
                    generation_metadata = dict(winner_metadata)
                    generation_metadata["selected_preprocessing"] = winner_profile
                    generation_metadata["observations"] = [item[2] for item in candidates]
                    generation_metadata["line_crop_quality"] = quality
                    generation_metadata["quality_warning"] = quality["quality_warning"]
                    generation_metadata["quality_warnings"] = quality["warnings"]
                    repository.record_success(
                        context.job.owner_session_id,
                        run_id,
                        region,
                        crop,
                        raw_text=winner.text,
                        generation=generation_metadata,
                        duration_ms=sum(item[1].duration_ms for item in candidates),
                    )
            except RecognitionInputInvalid as error:
                raise TerminalJobError(str(error)) from error
            except TrocrRuntimeError as error:
                runtime.close()
                for region, crop in crops:
                    repository.record_failure(
                        context.job.owner_session_id,
                        run_id,
                        region,
                        crop,
                        error_code=str(error),
                        retryable=True,
                    )
            finally:
                for images in profile_images.values():
                    for image in images:
                        image.close()
            results = repository.latest_results(context.job.owner_session_id, run_id)
            observed = sum(result.state in settled_states for result in results.values())
            processed = max(processed, observed)
            context.advance_progress("recognizing_lines", processed_count=processed, total_count=total)
    finally:
        if prepared_image is not None:
            prepared_image.close()

    results = repository.latest_results(context.job.owner_session_id, run_id)
    has_partial = any(result.state != "completed" for result in results.values())
    context.complete_stage("recognizing_lines", processed_count=processed, total_count=total, partial=has_partial)
    try:
        _, assembled_partial = repository.assemble_raw_page(context.job.owner_session_id, run_id)
    except RecognitionRunNotFound as error:
        raise TerminalJobError("recognition_run_input_missing") from error
    context.complete_stage("assembling", processed_count=processed, total_count=total, partial=assembled_partial)
    context.complete_stage("ready_for_review", processed_count=processed, total_count=total, partial=assembled_partial)
    return JobResult("partial" if assembled_partial else "completed")


def _recognize_confirmed_lines_gemini(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    runtime: GeminiOcrRuntime,
) -> JobResult:
    repository = RecognitionRepository(database, storage)
    run_id = context.repository.active_run_id(context.job.id)
    batch_size = 8
    generation_parameters = {
        "provider": "openrouter",
        "model": runtime.model,
        "mode": settings.gemini_mode,
        "batch_size": batch_size,
        "thinking_level": settings.gemini_thinking_level,
        "provider_sort": "price",
        "max_prompt_price": runtime.max_prompt_price,
        "max_completion_price": runtime.max_completion_price,
    }
    context.repository.set_run_metadata(
        context.job.id,
        context.worker_id,
        model_manifest_sha256=None,
        pipeline_manifest_sha256=None,
        trocr_model_version=None,
        rslora_adapter_version=None,
        device="cloud",
        dtype="provider_managed",
        generation_parameters_json=json.dumps(generation_parameters, sort_keys=True, separators=(",", ":")),
    )
    prepared_image: Image.Image | None = None
    try:
        regions = repository.run_regions(context.job.owner_session_id, run_id)
        prepared_key = repository.prepared_storage_key(context.job.owner_session_id, run_id)
        with Image.open(storage.resolve(prepared_key)) as source:
            prepared_image = source.convert("RGB")
    except RecognitionRunNotFound as error:
        raise TerminalJobError("recognition_run_input_missing") from error
    except OSError as error:
        raise TerminalJobError("recognition_prepared_page_decode_failed") from error

    total = len(regions)
    results = repository.latest_results(context.job.owner_session_id, run_id)
    settled_states = {"completed", "failed_retryable", "failed_terminal"}
    processed = max(context.job.processed_count, sum(result.state in settled_states for result in results.values()))
    pending_regions = [
        region
        for region in regions
        if (prior := results.get(region.id)) is None or prior.state not in {"completed", "failed_terminal"}
    ]
    try:
        for offset in range(0, len(pending_regions), batch_size):
            context.checkpoint()
            batch = pending_regions[offset:offset + batch_size]
            crops: list[tuple[RunRegion, StoredCrop]] = []
            images: list[Image.Image] = []
            qualities: list[dict[str, object]] = []
            try:
                for region in batch:
                    crop = repository.crop_for_region(
                        context.job.owner_session_id,
                        run_id,
                        region,
                        prepared_image,
                        padding_fraction=settings.line_crop_padding,
                    )
                    crops.append((region, crop))
                    with Image.open(storage.resolve(crop.storage_key)) as crop_image:
                        rectified = crop_image.convert("RGB")
                    images.append(rectified)
                    qualities.append(assess_line_crop(rectified))
                response = runtime.recognize_crops(images)
                if len(response.lines) != len(crops):
                    raise GeminiRuntimeError("gemini_line_count_mismatch")
                per_line_duration = response.duration_ms // max(1, len(crops))
                for (region, crop), quality, generation in zip(crops, qualities, response.lines, strict=True):
                    repository.record_success(
                        context.job.owner_session_id,
                        run_id,
                        region,
                        crop,
                        raw_text=generation.text,
                        generation={
                            "provider": "openrouter",
                            "selected_provider": response.usage.provider,
                            "model": runtime.model.removesuffix(":floor"),
                            "thinking_level": settings.gemini_thinking_level,
                            "batch_usage": asdict(response.usage),
                            "line_crop_quality": quality,
                            "quality_warning": quality["quality_warning"],
                            "quality_warnings": quality["warnings"],
                        },
                        duration_ms=per_line_duration,
                    )
            except RecognitionInputInvalid as error:
                raise TerminalJobError(str(error)) from error
            except GeminiRuntimeError as error:
                for region, crop in crops:
                    repository.record_failure(
                        context.job.owner_session_id,
                        run_id,
                        region,
                        crop,
                        error_code=str(error).split(":", 1)[0],
                        retryable=True,
                    )
            finally:
                for image in images:
                    image.close()
            results = repository.latest_results(context.job.owner_session_id, run_id)
            processed = max(processed, sum(result.state in settled_states for result in results.values()))
            context.advance_progress("recognizing_lines", processed_count=processed, total_count=total)
    finally:
        if prepared_image is not None:
            prepared_image.close()

    results = repository.latest_results(context.job.owner_session_id, run_id)
    has_partial = len(results) != total or any(result.state != "completed" for result in results.values())
    context.complete_stage("recognizing_lines", processed_count=processed, total_count=total, partial=has_partial)
    try:
        _, assembled_partial = repository.assemble_raw_page(context.job.owner_session_id, run_id)
    except RecognitionRunNotFound as error:
        raise TerminalJobError("recognition_run_input_missing") from error
    context.complete_stage("assembling", processed_count=processed, total_count=total, partial=assembled_partial)
    context.complete_stage("ready_for_review", processed_count=processed, total_count=total, partial=assembled_partial)
    return JobResult("partial" if assembled_partial else "completed")


def run_page_recognition(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    models_root: Path,
    craft_runtime: CraftRuntime | None,
    trocr_runtime: TrocrRuntime | None,
    kraken_runtime: KrakenRuntime | None = None,
    gemini_runtime: GeminiOcrRuntime | None = None,
    close_runtime: bool = True,
) -> JobResult:
    """Execute one durable phase; region confirmation is the only bridge between ML models."""
    stage = context.job.stage
    completed = context.completed_stages
    if stage == "recognizing_lines" or stage in {"assembling", "ready_for_review"}:
        if _recognize_demo_preset(context, database, storage):
            return JobResult("completed")
        if gemini_runtime is not None:
            if gemini_runtime is None:
                raise RetryableJobError("gemini_runtime_unavailable")
            try:
                return _recognize_confirmed_lines_gemini(
                    context,
                    database=database,
                    storage=storage,
                    runtime=gemini_runtime,
                )
            finally:
                if close_runtime:
                    gemini_runtime.close()
        if trocr_runtime is None:
            raise RetryableJobError("trocr_runtime_unavailable")
        try:
            return _recognize_confirmed_lines(
                context,
                database=database,
                storage=storage,
                runtime=trocr_runtime,
            )
        finally:
            if close_runtime:
                trocr_runtime.close()
    if "detecting_regions" in completed:
        return JobResult("awaiting_region_review")
    if stage not in {"validating", "preprocessing", "detecting_regions", "queued"}:
        raise RetryableJobError("recognition_stage_invalid")
    if _apply_demo_regions(context, database):
        return JobResult("awaiting_region_review")
    detector_runtime: CraftRuntime | KrakenRuntime | GeminiOcrRuntime | None
    if gemini_runtime is not None and settings.gemini_mode == "page":
        detector_runtime = gemini_runtime
    else:
        detector_runtime = craft_runtime or kraken_runtime
    if detector_runtime is None:
        raise RetryableJobError("detector_runtime_unavailable")
    try:
        return _detect_regions(
            context,
            database=database,
            storage=storage,
            models_root=models_root,
            runtime=detector_runtime,
        )
    finally:
        if close_runtime:
            detector_runtime.close()


def _json_protocol_output(output: str) -> dict[str, object] | None:
    """Read the final structured child message without exposing child output."""
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _worker_command(*arguments: str) -> list[str]:
    return [sys.executable, "-m", "app.worker.main", *arguments]


def _phase_command(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    models_root: Path,
    device: str | None = None,
    craft_max_edge: int | None = None,
) -> list[str]:
    return _worker_command(
        "--phase-job",
        context.job.id,
        "--worker-id",
        context.worker_id,
        "--database",
        str(database.path),
        "--storage",
        str(storage.root),
        "--models",
        str(models_root),
        "--lease-seconds",
        str(context.lease_seconds),
        "--device",
        device or settings.ml_device,
        "--craft-max-edge",
        str(craft_max_edge or settings.craft_max_edge),
    )


def _run_phase_subprocess(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    models_root: Path,
    device: str | None = None,
    craft_max_edge: int | None = None,
) -> JobResult:
    """Run exactly one CRAFT or TrOCR phase in a fresh process.

    CRAFT and TrOCR are both substantial models.  Keeping the coordinator
    lightweight and assigning each durable phase a child process ensures that
    allocator state and model graphs from the completed phase are gone before
    the next model is loaded.  The database remains the sole handoff channel.
    """
    try:
        completed = subprocess.run(
            _phase_command(
                context,
                database=database,
                storage=storage,
                models_root=models_root,
                device=device,
                craft_max_edge=craft_max_edge,
            ),
            cwd=Path(__file__).resolve().parents[2],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(1800, context.lease_seconds * 4),
            check=False,
        )
    except subprocess.TimeoutExpired as error:
        raise RetryableJobError("worker_phase_timeout") from error
    except OSError as error:
        raise RetryableJobError("worker_phase_spawn_failed") from error

    payload = _json_protocol_output(completed.stdout)
    if completed.returncode != 0 and completed.stderr.strip():
        logging.getLogger(__name__).error(
            "worker_phase_stderr job_id=%s details=%s",
            context.job.id,
            completed.stderr.strip()[-4000:],
        )
    if payload is None:
        raise RetryableJobError("worker_phase_crashed")
    status = payload.get("status")
    if status == "ok" and completed.returncode == 0:
        state = payload.get("state")
        if isinstance(state, str):
            return JobResult(state)
    if status == "cancelled":
        raise JobCancelled
    if status == "retryable":
        code = payload.get("code")
        raise RetryableJobError(code if isinstance(code, str) else "worker_phase_retryable")
    if status == "terminal":
        code = payload.get("code")
        raise TerminalJobError(code if isinstance(code, str) else "worker_phase_terminal")
    if status == "lost_lease":
        raise LostLease(context.job.id)
    if status == "error":
        error_type = payload.get("error_type")
        if error_type == "OperationalError":
            raise RetryableJobError("worker_phase_database_error")
        if error_type == "PermissionError":
            raise RetryableJobError("worker_phase_storage_access_error")
        raise RetryableJobError("worker_phase_crashed")
    raise RetryableJobError("worker_phase_crashed")


def _warmup_command(model_name: str, *, models_root: Path) -> list[str]:
    return _worker_command(
        "--warmup-model",
        model_name,
        "--models",
        str(models_root),
        "--device",
        settings.ml_device,
        "--craft-max-edge",
        str(settings.craft_max_edge),
    )


def _probe_model(model_name: str, *, models_root: Path) -> tuple[str, str | None, dict[str, object] | None, str | None]:
    """Warm a model in its own short-lived process and return sanitized evidence."""
    try:
        completed = subprocess.run(
            _warmup_command(model_name, models_root=models_root),
            cwd=Path(__file__).resolve().parents[2],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=max(300, settings.worker_lease_seconds * 2),
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unavailable", None, None, "worker_model_probe_failed"
    payload = _json_protocol_output(completed.stdout)
    if completed.returncode != 0 or payload is None or payload.get("status") != "ready":
        code = payload.get("code") if payload is not None else None
        return "unavailable", None, None, code if isinstance(code, str) else "worker_model_probe_failed"
    evidence = payload.get("evidence")
    if not isinstance(evidence, dict):
        return "unavailable", None, None, "worker_model_probe_invalid"
    version = evidence.get("model_version")
    return "ready", version if isinstance(version, str) else None, evidence, None


def _record_startup_readiness(repository: JobRepository, worker_id: str, *, models_root: Path) -> None:
    detector_name = "craft" if settings.craft_enabled else "kraken"
    for model_name in (detector_name, "trocr"):
        status, model_version, evidence, error_code = _probe_model(model_name, models_root=models_root)
        repository.record_model_readiness(
            worker_id,
            model_name,
            status=status,
            model_version=model_version,
            evidence=evidence,
            error_code=error_code,
        )


def _warm_persistent_runtimes(
    repository: JobRepository,
    worker_id: str,
    *,
    models_root: Path,
) -> tuple[CraftRuntime | None, KrakenRuntime | None, TrocrRuntime | None, GeminiOcrRuntime | None]:
    """Load each model once in the worker process and persist its true readiness."""
    craft_runtime: CraftRuntime | None = None
    kraken_runtime: KrakenRuntime | None = None
    gemini_runtime: GeminiOcrRuntime | None = None
    if settings.ocr_provider == "gemini":
        try:
            gemini_runtime = GeminiOcrRuntime(
                api_key=settings.openrouter_api_key,
                model=settings.gemini_model,
                timeout_seconds=settings.gemini_timeout_seconds,
                thinking_level=settings.gemini_thinking_level,
                max_output_tokens=settings.gemini_max_output_tokens,
                max_page_regions=settings.gemini_max_page_regions,
            )
        except GeminiRuntimeError as error:
            repository.record_model_readiness(
                worker_id,
                "gemini_openrouter",
                status="unavailable",
                model_version=settings.gemini_model.removesuffix(":floor"),
                evidence=None,
                error_code=str(error),
            )
            return None, None, None, None

    detector_runtime: CraftRuntime | KrakenRuntime | GeminiOcrRuntime
    if settings.ocr_provider == "gemini" and settings.gemini_mode == "page":
        detector_name = "gemini_openrouter"
        assert gemini_runtime is not None
        detector_runtime = gemini_runtime
    elif settings.ocr_provider == "gemini" or not settings.craft_enabled:
        detector_name = "kraken"
        kraken_runtime = KrakenRuntime(
            settings.kraken_endpoint,
            timeout_seconds=settings.kraken_timeout_seconds,
        )
        detector_runtime = kraken_runtime
    else:
        detector_name = "craft"
        craft_runtime = CraftRuntime(
            models_root,
            max_edge=settings.craft_max_edge,
            device=settings.ml_device,
        )
        detector_runtime = craft_runtime
    trocr_runtime: TrocrRuntime | None = None
    if settings.ocr_provider == "trocr":
        trocr_runtime = TrocrRuntime(
            models_root,
            device=settings.ml_device,
            adapter_mode=settings.trocr_adapter_mode,
        )

    try:
        detector_runtime.warmup()
        detector_evidence = detector_runtime.evidence
        if detector_evidence is None:
            raise RuntimeError("detector_readiness_evidence_missing")
        repository.record_model_readiness(
            worker_id,
            detector_name,
            status="ready",
            model_version=detector_evidence.model_version,
            evidence=asdict(detector_evidence),
            error_code=None,
        )
    except Exception as error:
        logging.getLogger(__name__).exception("worker_detector_warmup_failed detector=%s", detector_name)
        repository.record_model_readiness(
            worker_id,
            detector_name,
            status="unavailable",
            model_version=None,
            evidence=None,
            error_code=(
                str(error)
                if isinstance(error, (CraftRuntimeError, KrakenRuntimeError, GeminiRuntimeError))
                else "worker_model_probe_failed"
            ),
        )
        detector_runtime.close()
        craft_runtime = None
        kraken_runtime = None
        if detector_name == "gemini_openrouter":
            gemini_runtime = None

    if settings.ocr_provider == "gemini":
        if gemini_runtime is not None and detector_name != "gemini_openrouter":
            evidence = gemini_runtime.evidence
            repository.record_model_readiness(
                worker_id,
                "gemini_openrouter",
                status="ready",
                model_version=evidence.model_version,
                evidence=asdict(evidence),
                error_code=None,
            )
        return craft_runtime, kraken_runtime, None, gemini_runtime

    assert trocr_runtime is not None
    try:
        trocr_evidence = trocr_runtime.warmup()
        repository.record_model_readiness(
            worker_id,
            "trocr",
            status="ready",
            model_version=trocr_evidence.model_version,
            evidence=asdict(trocr_evidence),
            error_code=None,
        )
    except Exception as error:
        logging.getLogger(__name__).exception("worker_trocr_warmup_failed")
        repository.record_model_readiness(
            worker_id,
            "trocr",
            status="unavailable",
            model_version=None,
            evidence=None,
            error_code=str(error) if isinstance(error, TrocrRuntimeError) else "worker_model_probe_failed",
        )
        trocr_runtime.close()
        trocr_runtime = None

    return craft_runtime, kraken_runtime, trocr_runtime, None


def _run_phase(arguments: argparse.Namespace) -> int:
    database = Database(Path(arguments.database).resolve())
    storage = FileStorage(Path(arguments.storage).resolve())
    repository = JobRepository(database)
    try:
        job = repository.get_internal(arguments.phase_job)
        context = JobContext(repository, job, arguments.worker_id, arguments.lease_seconds)
        recognition_phase = job.stage in {"recognizing_lines", "assembling", "ready_for_review"}
        result = run_page_recognition(
            context,
            database=database,
            storage=storage,
            models_root=Path(arguments.models).resolve(),
            craft_runtime=(
                CraftRuntime(
                    Path(arguments.models).resolve(),
                    max_edge=arguments.craft_max_edge,
                    device=arguments.device,
                )
                if not recognition_phase and settings.ocr_provider == "trocr" and settings.craft_enabled
                else None
            ),
            kraken_runtime=(
                KrakenRuntime(
                    settings.kraken_endpoint,
                    timeout_seconds=settings.kraken_timeout_seconds,
                )
                if (
                    not recognition_phase
                    and not settings.craft_enabled
                    and (settings.ocr_provider == "trocr" or settings.gemini_mode == "kraken")
                )
                else None
            ),
            trocr_runtime=TrocrRuntime(
                Path(arguments.models).resolve(),
                device=arguments.device,
                adapter_mode=settings.trocr_adapter_mode,
            )
            if recognition_phase and settings.ocr_provider == "trocr"
            else None,
            gemini_runtime=(
                GeminiOcrRuntime(
                    api_key=settings.openrouter_api_key,
                    model=settings.gemini_model,
                    timeout_seconds=settings.gemini_timeout_seconds,
                    thinking_level=settings.gemini_thinking_level,
                    max_output_tokens=settings.gemini_max_output_tokens,
                    max_page_regions=settings.gemini_max_page_regions,
                )
                if settings.ocr_provider == "gemini"
                else None
            ),
        )
    except JobCancelled:
        print(json.dumps({"status": "cancelled"}, sort_keys=True), flush=True)
        return 0
    except RetryableJobError as error:
        print(json.dumps({"status": "retryable", "code": error.code}, sort_keys=True), flush=True)
        return 1
    except TerminalJobError as error:
        print(json.dumps({"status": "terminal", "code": error.code}, sort_keys=True), flush=True)
        return 1
    except LostLease:
        print(json.dumps({"status": "lost_lease"}, sort_keys=True), flush=True)
        return 1
    except Exception as error:
        error_type = type(error).__name__
        logging.getLogger(__name__).exception("worker_phase_failed error_type=%s", error_type)
        print(
            json.dumps({"status": "error", "code": "worker_phase_crashed", "error_type": error_type}, sort_keys=True),
            flush=True,
        )
        return 1
    print(json.dumps({"status": "ok", "state": result.state}, sort_keys=True), flush=True)
    return 0


def _warmup_model(arguments: argparse.Namespace) -> int:
    models_root = Path(arguments.models).resolve()
    try:
        if arguments.warmup_model == "craft":
            runtime = CraftRuntime(models_root, max_edge=arguments.craft_max_edge, device=arguments.device)
            try:
                runtime.warmup()
                evidence: Any = runtime.evidence
            finally:
                runtime.close()
        elif arguments.warmup_model == "kraken":
            runtime = KrakenRuntime(
                settings.kraken_endpoint,
                timeout_seconds=settings.kraken_timeout_seconds,
            )
            try:
                evidence = runtime.warmup()
            finally:
                runtime.close()
        else:
            runtime = TrocrRuntime(
                models_root,
                device=arguments.device,
                adapter_mode=settings.trocr_adapter_mode,
            )
            try:
                evidence = runtime.warmup()
            finally:
                runtime.close()
        if evidence is None:
            raise RuntimeError("worker_model_probe_invalid")
    except (CraftRuntimeError, KrakenRuntimeError, TrocrRuntimeError) as error:
        print(json.dumps({"status": "unavailable", "code": str(error)}, sort_keys=True), flush=True)
        return 1
    except Exception:
        logging.getLogger(__name__).exception("worker_model_probe_failed model=%s", arguments.warmup_model)
        print(json.dumps({"status": "unavailable", "code": "worker_model_probe_failed"}, sort_keys=True), flush=True)
        return 1
    print(json.dumps({"status": "ready", "evidence": asdict(evidence)}, sort_keys=True), flush=True)
    return 0


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tajik HTR durable ML worker")
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--phase-job")
    action.add_argument("--warmup-model", choices=("craft", "kraken", "trocr"))
    parser.add_argument("--worker-id")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--storage", type=Path)
    parser.add_argument("--models", type=Path)
    parser.add_argument("--lease-seconds", type=int)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default=settings.ml_device)
    parser.add_argument("--craft-max-edge", type=int, default=settings.craft_max_edge)
    arguments = parser.parse_args()
    if arguments.phase_job:
        required = (arguments.worker_id, arguments.database, arguments.storage, arguments.models, arguments.lease_seconds)
        if not all(required) or arguments.lease_seconds < 1:
            parser.error("--phase-job requires --worker-id, --database, --storage, --models and positive --lease-seconds")
    elif arguments.warmup_model:
        if arguments.models is None:
            parser.error("--warmup-model requires --models")
    return arguments


def run() -> None:
    configure_logging()
    if settings.supabase_url and settings.supabase_key:
        from app.core.supabase_database import SupabaseDatabase
        from app.core.supabase_storage import SupabaseStorage
        database = SupabaseDatabase(settings.supabase_url, settings.supabase_key)
        storage = SupabaseStorage(settings.supabase_url, settings.supabase_key, settings.supabase_bucket)
    else:
        database = Database(settings.database_path)
        database.migrate()
        storage = FileStorage(settings.storage_root)
    models_root = Path(__file__).resolve().parents[2] / "models"
    worker_id = f"worker-{uuid4()}"
    started_at = _now()
    repository = JobRepository(database)
    repository.record_worker_heartbeat(worker_id, status="idle", current_job_id=None, started_at=started_at)
    craft_runtime, kraken_runtime, trocr_runtime, gemini_runtime = _warm_persistent_runtimes(
        repository,
        worker_id,
        models_root=models_root,
    )
    stop_event = threading.Event()
    service = WorkerService(
        repository,
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        handlers={
            "page_recognition": lambda context: run_page_recognition(
                context,
                database=database,
                storage=storage,
                models_root=models_root,
                craft_runtime=craft_runtime,
                kraken_runtime=kraken_runtime,
                trocr_runtime=trocr_runtime,
                gemini_runtime=gemini_runtime,
                close_runtime=False,
            )
        },
    )

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logging.getLogger(__name__).info("worker_started worker_id=%s", worker_id)
    try:
        service.run_forever(stop_event, poll_seconds=settings.worker_poll_seconds)
    finally:
        if craft_runtime is not None:
            craft_runtime.close()
        if kraken_runtime is not None:
            kraken_runtime.close()
        if trocr_runtime is not None:
            trocr_runtime.close()
        if gemini_runtime is not None:
            gemini_runtime.close()
        repository.record_worker_heartbeat(worker_id, status="stopped", current_job_id=None, started_at=started_at)


if __name__ == "__main__":
    cli_arguments = _parse_arguments()
    if cli_arguments.phase_job:
        raise SystemExit(_run_phase(cli_arguments))
    if cli_arguments.warmup_model:
        raise SystemExit(_warmup_model(cli_arguments))
    run()
