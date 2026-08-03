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
import zlib
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import cv2
import numpy as np
from PIL import Image

from app.core.database import Database
from app.core.logging import configure_logging
from app.core.settings import settings
from app.core.storage import FileStorage
from app.ml.craft_runtime import DEFAULT_THRESHOLDS, CraftDetection, CraftRuntime, CraftRuntimeError
from app.ml.kraken_runtime import KrakenDetection, KrakenRuntime, KrakenRuntimeError
from app.ml.trocr_runtime import TrocrRuntime, TrocrRuntimeError
from app.repositories.jobs import JobRepository, LostLease
from app.repositories.recognition import RecognitionInputInvalid, RecognitionRepository, RecognitionRunNotFound
from app.repositories.regions import RegionRepository, RegionRevisionConflict
from app.services.jobs import JobCancelled, JobContext, JobResult, RetryableJobError, TerminalJobError, WorkerService
from app.services.regions import (
    BoundingBox,
    DetectorComponent,
    GroupingParameters,
    LineCandidate,
    group_components,
    grouping_metrics,
    reading_order,
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


def _detect_regions(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    models_root: Path,
    runtime: CraftRuntime | KrakenRuntime,
) -> JobResult:
    context.checkpoint()
    page_revision, prepared_asset_id, prepared_sha256, storage_key, _ = _load_prepared_page(context, database)
    try:
        with Image.open(storage.resolve(storage_key)) as source:
            result = runtime.detect(source)
    except (CraftRuntimeError, KrakenRuntimeError) as error:
        raise RetryableJobError(str(error)) from error
    except OSError as error:
        raise TerminalJobError("detector_page_decode_failed") from error
    context.checkpoint()

    if isinstance(result, KrakenDetection):
        detector_name = "kraken"
        regions = []
        raw_lines = []
        for line in result.lines:
            try:
                polygon = _normalised_kraken_quad(line.boundary, width=result.width, height=result.height)
            except ValueError:
                continue
            flags = ["kraken_blla", "boundary_min_area_quad"]
            if not line.baseline:
                flags.append("baseline_missing")
            regions.append(
                {
                    "polygon": polygon,
                    "reading_order": len(regions),
                    "source": "kraken",
                    "flags": flags,
                    "detector_version": result.detector_version,
                    "detector_score": None,
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
            "region_count": len(regions),
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
        if len(line_candidates) == 1 and line_candidates[0].bbox.width < 0.9:
            candidate = line_candidates[0]
            line_candidates = [
                LineCandidate(
                    BoundingBox(0.0, candidate.bbox.top, 1.0, candidate.bbox.bottom),
                    candidate.component_ids,
                    candidate.score,
                    tuple(dict.fromkeys((*candidate.flags, "single_line_full_width"))),
                )
            ]
        regions = [
            {
                "polygon": _rectangle(candidate.bbox),
                "reading_order": order,
                "source": "craft",
                "flags": list(candidate.flags),
                "detector_version": result.detector_version,
                "detector_score": candidate.score,
            }
            for order, candidate in enumerate(line_candidates)
        ]
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
    context.complete_stage("detecting_regions", processed_count=1, total_count=1)
    return JobResult("awaiting_region_review")


def _line_generation_metadata(generation: object, *, num_beams: int, max_new_tokens: int) -> dict[str, object]:
    return {
        "num_beams": num_beams,
        "max_new_tokens": max_new_tokens,
        "generated_token_count": generation.generated_token_count,
        "decoding_steps": generation.decoding_steps,
        "mean_token_log_probability": generation.mean_token_log_probability,
    }


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
            crops = []
            images: list[Image.Image] = []
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
                        images.append(crop_image.convert("RGB"))
                if batch_size == 1:
                    generations = (
                        runtime.recognize(
                            images[0],
                            num_beams=settings.trocr_num_beams,
                            max_new_tokens=settings.trocr_max_new_tokens,
                        ),
                    )
                else:
                    generations = runtime.recognize_many(
                        images,
                        num_beams=settings.trocr_num_beams,
                        max_new_tokens=settings.trocr_max_new_tokens,
                    )
                if len(generations) != len(crops):
                    raise TrocrRuntimeError("trocr_batch_result_count_mismatch")
                for (region, crop), generation in zip(crops, generations, strict=True):
                    repository.record_success(
                        context.job.owner_session_id,
                        run_id,
                        region,
                        crop,
                        raw_text=generation.text,
                        generation=_line_generation_metadata(
                            generation,
                            num_beams=settings.trocr_num_beams,
                            max_new_tokens=settings.trocr_max_new_tokens,
                        ),
                        duration_ms=generation.duration_ms,
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


def run_page_recognition(
    context: JobContext,
    *,
    database: Database,
    storage: FileStorage,
    models_root: Path,
    craft_runtime: CraftRuntime | None,
    trocr_runtime: TrocrRuntime | None,
    kraken_runtime: KrakenRuntime | None = None,
    close_runtime: bool = True,
) -> JobResult:
    """Execute one durable phase; region confirmation is the only bridge between ML models."""
    stage = context.job.stage
    completed = context.completed_stages
    if stage == "recognizing_lines" or stage in {"assembling", "ready_for_review"}:
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
) -> tuple[CraftRuntime | None, KrakenRuntime | None, TrocrRuntime | None]:
    """Load each model once in the worker process and persist its true readiness."""
    craft_runtime: CraftRuntime | None = None
    kraken_runtime: KrakenRuntime | None = None
    detector_name = "craft" if settings.craft_enabled else "kraken"
    detector_runtime: CraftRuntime | KrakenRuntime
    if settings.craft_enabled:
        craft_runtime = CraftRuntime(
            models_root,
            max_edge=settings.craft_max_edge,
            device=settings.ml_device,
        )
        detector_runtime = craft_runtime
    else:
        kraken_runtime = KrakenRuntime(
            settings.kraken_endpoint,
            timeout_seconds=settings.kraken_timeout_seconds,
        )
        detector_runtime = kraken_runtime
    trocr_runtime: TrocrRuntime | None = TrocrRuntime(models_root, device=settings.ml_device)

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
                if isinstance(error, (CraftRuntimeError, KrakenRuntimeError))
                else "worker_model_probe_failed"
            ),
        )
        detector_runtime.close()
        craft_runtime = None
        kraken_runtime = None

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

    return craft_runtime, kraken_runtime, trocr_runtime


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
                if not recognition_phase and settings.craft_enabled
                else None
            ),
            kraken_runtime=(
                KrakenRuntime(
                    settings.kraken_endpoint,
                    timeout_seconds=settings.kraken_timeout_seconds,
                )
                if not recognition_phase and not settings.craft_enabled
                else None
            ),
            trocr_runtime=TrocrRuntime(Path(arguments.models).resolve(), device=arguments.device)
            if recognition_phase
            else None,
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
            runtime = TrocrRuntime(models_root, device=arguments.device)
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
    database = Database(settings.database_path)
    database.migrate()
    storage = FileStorage(settings.storage_root)
    models_root = Path(__file__).resolve().parents[2] / "models"
    worker_id = f"worker-{uuid4()}"
    started_at = _now()
    repository = JobRepository(database)
    repository.record_worker_heartbeat(worker_id, status="idle", current_job_id=None, started_at=started_at)
    craft_runtime, kraken_runtime, trocr_runtime = _warm_persistent_runtimes(
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
        repository.record_worker_heartbeat(worker_id, status="stopped", current_job_id=None, started_at=started_at)


if __name__ == "__main__":
    cli_arguments = _parse_arguments()
    if cli_arguments.phase_job:
        raise SystemExit(_run_phase(cli_arguments))
    if cli_arguments.warmup_model:
        raise SystemExit(_warmup_model(cli_arguments))
    run()
