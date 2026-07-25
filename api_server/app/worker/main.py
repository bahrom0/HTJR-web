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

from PIL import Image

from app.core.database import Database
from app.core.logging import configure_logging
from app.core.settings import settings
from app.core.storage import FileStorage
from app.ml.craft_runtime import DEFAULT_THRESHOLDS, CraftRuntime, CraftRuntimeError
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


def _pipeline_manifest_sha256(models_root: Path) -> str | None:
    """Hash only local, versioned model manifests; never inspect image content."""
    entries = {
        "craft": _sha256(models_root / "craft" / "manifest.json"),
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
    runtime: CraftRuntime,
) -> JobResult:
    context.checkpoint()
    page_revision, prepared_asset_id, prepared_sha256, storage_key, _ = _load_prepared_page(context, database)
    try:
        with Image.open(storage.resolve(storage_key)) as source:
            result = runtime.detect(source)
    except CraftRuntimeError as error:
        raise RetryableJobError(str(error)) from error
    except OSError as error:
        raise TerminalJobError("craft_page_decode_failed") from error
    context.checkpoint()

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
        # A single handwritten line may occupy only the centre of a phone
        # photo. Keep the detector's tight vertical geometry while retaining
        # the full horizontal canvas so low-confidence edge characters are not
        # clipped before TrOCR receives the crop.
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
    try:
        persisted_page_revision = RegionRepository(database).replace(
            context.job.owner_session_id,
            context.job.page_id,
            page_revision,
            regions,
        )
    except RegionRevisionConflict as error:
        raise RetryableJobError("craft_region_revision_conflict") from error

    repository = context.repository
    run_id = repository.active_run_id(context.job.id)
    threshold_payload = {"version": result.thresholds_version, "values": DEFAULT_THRESHOLDS}
    manifest_sha256 = _pipeline_manifest_sha256(models_root)
    repository.set_run_metadata(
        context.job.id,
        context.worker_id,
        model_manifest_sha256=manifest_sha256,
        pipeline_manifest_sha256=manifest_sha256,
        prepared_asset_id=prepared_asset_id,
        prepared_asset_sha256=prepared_sha256,
        page_revision=persisted_page_revision,
        craft_detector_version=result.detector_version,
        craft_thresholds_json=json.dumps(threshold_payload, sort_keys=True, separators=(",", ":")),
    )
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
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO craft_detector_outputs(
                   id,owner_session_id,page_id,job_id,recognition_run_id,detector_version,thresholds_json,output_json,created_at)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (
                str(uuid4()),
                context.job.owner_session_id,
                context.job.page_id,
                context.job.id,
                run_id,
                result.detector_version,
                json.dumps(threshold_payload, sort_keys=True, separators=(",", ":")),
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

    try:
        for region in regions:
            context.checkpoint()
            prior = results.get(region.id)
            if prior is not None and prior.state in {"completed", "failed_terminal"}:
                continue
            try:
                crop = repository.crop_for_region(
                    context.job.owner_session_id,
                    run_id,
                    region,
                    prepared_image,
                    padding_fraction=settings.line_crop_padding,
                )
            except RecognitionInputInvalid as error:
                raise TerminalJobError(str(error)) from error
            try:
                with Image.open(storage.resolve(crop.storage_key)) as crop_image:
                    generation = runtime.recognize(
                        crop_image,
                        num_beams=settings.trocr_num_beams,
                        max_new_tokens=settings.trocr_max_new_tokens,
                    )
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
            except TrocrRuntimeError as error:
                runtime.close()
                repository.record_failure(
                    context.job.owner_session_id,
                    run_id,
                    region,
                    crop,
                    error_code=str(error),
                    retryable=True,
                )
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
) -> JobResult:
    """Execute one durable phase; region confirmation is the only bridge between ML models."""
    stage = context.job.stage
    completed = context.completed_stages
    if stage == "recognizing_lines" or stage in {"assembling", "ready_for_review"}:
        # A recognition subprocess never constructs or closes CRAFT: importing
        # its torch/torchvision cleanup path would unnecessarily expand the
        # TrOCR process memory footprint.
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
            trocr_runtime.close()
    if "detecting_regions" in completed:
        return JobResult("awaiting_region_review")
    if stage not in {"validating", "preprocessing", "detecting_regions", "queued"}:
        raise RetryableJobError("recognition_stage_invalid")
    # The detector subprocess never constructs or closes TrOCR.  The durable
    # job/region snapshot is the only boundary between the two model processes.
    if craft_runtime is None:
        raise RetryableJobError("craft_runtime_unavailable")
    try:
        return _detect_regions(
            context,
            database=database,
            storage=storage,
            models_root=models_root,
            runtime=craft_runtime,
        )
    finally:
        craft_runtime.close()


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
    for model_name in ("craft", "trocr"):
        status, model_version, evidence, error_code = _probe_model(model_name, models_root=models_root)
        repository.record_model_readiness(
            worker_id,
            model_name,
            status=status,
            model_version=model_version,
            evidence=evidence,
            error_code=error_code,
        )


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
            craft_runtime=None
            if recognition_phase
            else CraftRuntime(
                Path(arguments.models).resolve(),
                max_edge=arguments.craft_max_edge,
                device=arguments.device,
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
        else:
            runtime = TrocrRuntime(models_root, device=arguments.device)
            try:
                evidence = runtime.warmup()
            finally:
                runtime.close()
        if evidence is None:
            raise RuntimeError("worker_model_probe_invalid")
    except (CraftRuntimeError, TrocrRuntimeError) as error:
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
    action.add_argument("--warmup-model", choices=("craft", "trocr"))
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
    _record_startup_readiness(repository, worker_id, models_root=models_root)
    stop_event = threading.Event()
    service = WorkerService(
        repository,
        worker_id=worker_id,
        lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds,
        handlers={
            "page_recognition": lambda context: _run_phase_subprocess(
                context,
                database=database,
                storage=storage,
                models_root=models_root,
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
        repository.record_worker_heartbeat(worker_id, status="stopped", current_job_id=None, started_at=started_at)


if __name__ == "__main__":
    cli_arguments = _parse_arguments()
    if cli_arguments.phase_job:
        raise SystemExit(_run_phase(cli_arguments))
    if cli_arguments.warmup_model:
        raise SystemExit(_warmup_model(cli_arguments))
    run()
