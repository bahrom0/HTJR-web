from __future__ import annotations

"""Exercise the public HTTP handoff and the real persisted ML worker in one local process."""

import argparse
import io
import hashlib
import json
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

import app.main as main_module
from app.services.images import source_to_rgb
from app.services.jobs import WorkerService
from app.worker.main import _run_phase_subprocess


def _representative_page_payload(
    image_path: Path,
    *,
    compose_page: bool,
) -> tuple[bytes, list[dict[str, object]]]:
    """Use real handwritten source pixels while exercising a multi-line page.

    The repository fixture set contains cropped handwritten lines rather than
    scanned full pages.  For an end-to-end page test we place three copies on
    a white page with deterministic spacing; no model output or synthetic
    glyphs are introduced.
    """
    with Image.open(image_path) as source:
        line = source_to_rgb(source)
    if not compose_page:
        encoded = io.BytesIO()
        line.save(encoded, format="PNG")
        return encoded.getvalue(), []
    margin, gap = 28, max(32, line.height // 2)
    page = Image.new("RGB", (line.width + margin * 2, margin * 2 + line.height * 3 + gap * 2), "white")
    try:
        review_regions: list[dict[str, object]] = []
        for index in range(3):
            top = margin + index * (line.height + gap)
            page.paste(line, (margin, top))
            review_regions.append(
                {
                    # These are explicit review edits made by this HTTP test,
                    # not a post-detector heuristic.  The real CRAFT output is
                    # persisted and inspected first; only then does the test
                    # perform the same adjusted-region action as a reviewer.
                    "polygon": [
                        {"x": margin / page.width, "y": top / page.height},
                        {"x": (margin + line.width) / page.width, "y": top / page.height},
                        {"x": (margin + line.width) / page.width, "y": (top + line.height) / page.height},
                        {"x": margin / page.width, "y": (top + line.height) / page.height},
                    ],
                    "reading_order": index,
                    "source": "adjusted",
                    "flags": [],
                }
            )
        encoded = io.BytesIO()
        page.save(encoded, format="PNG")
        return encoded.getvalue(), review_regions
    finally:
        line.close()
        page.close()


def _remove_temporary_root(root: Path) -> None:
    """Wait out short-lived SQLite handles without retaining test images on Windows."""
    for attempt in range(8):
        try:
            shutil.rmtree(root)
            return
        except FileNotFoundError:
            return
        except PermissionError:
            if attempt == 7:
                raise
            time.sleep(0.25)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument(
        "--compose-page",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Place three real handwritten lines on a deterministic verification page (default).",
    )
    arguments = parser.parse_args()
    if not arguments.image.is_file():
        parser.error("--image must be a readable local image")
    upload_payload, review_regions = _representative_page_payload(
        arguments.image,
        compose_page=arguments.compose_page,
    )

    original_settings = main_module.settings
    with tempfile.TemporaryDirectory(prefix="tajik-htr-http-", ignore_cleanup_errors=True) as temporary:
        root = Path(temporary)
        main_module.settings = replace(
            original_settings,
            database_path=root / "studio.sqlite3",
            storage_root=root / "assets",
        )
        try:
            with TestClient(main_module.create_app()) as client:
                register = client.post(
                    "/api/v1/access/register",
                    json={
                        "email": "verification@example.test",
                        "name": "Runtime Verification",
                        "password": "correct horse battery",
                    },
                )
                if register.status_code != 201:
                    raise RuntimeError(f"register_http_{register.status_code}")
                csrf = register.json()["csrf_token"]
                upload = client.post(
                    "/api/v1/documents",
                    content=upload_payload,
                    headers={
                        "Content-Type": "image/png",
                        "Idempotency-Key": "http-runtime-upload-001",
                        "X-CSRF-Token": csrf,
                    },
                )
                if upload.status_code != 201:
                    raise RuntimeError(f"upload_http_{upload.status_code}")
                page_id = upload.json()["page_id"]
                prepared = client.post(
                    f"/api/v1/pages/{page_id}/prepare",
                    json={},
                    headers={"X-CSRF-Token": csrf},
                )
                if prepared.status_code != 200:
                    raise RuntimeError(f"prepare_http_{prepared.status_code}")
                preparation = client.get(f"/api/v1/pages/{page_id}/preparation")
                confirmation = client.post(
                    f"/api/v1/pages/{page_id}/preparation/confirm",
                    json={"revision": preparation.json()["revision"]},
                    headers={"X-CSRF-Token": csrf},
                )
                if confirmation.status_code != 200:
                    raise RuntimeError(f"preparation_confirm_http_{confirmation.status_code}")
                job_response = client.post(
                    f"/api/v1/pages/{page_id}/recognition-jobs",
                    json={"priority": 0},
                    headers={"Idempotency-Key": "http-runtime-recognition-001", "X-CSRF-Token": csrf},
                )
                if job_response.status_code != 201:
                    raise RuntimeError(f"job_create_http_{job_response.status_code}")
                job_id = job_response.json()["id"]

                models_root = Path(__file__).resolve().parents[1] / "models"
                handler = lambda context: _run_phase_subprocess(
                    context,
                    database=client.app.state.database,
                    storage=client.app.state.storage,
                    models_root=models_root,
                    device=arguments.device,
                )
                WorkerService(
                    client.app.state.jobs,
                    worker_id="http-verify-detector",
                    lease_seconds=90,
                    handlers={"page_recognition": handler},
                ).run_once()
                waiting = client.get(f"/api/v1/jobs/{job_id}").json()
                if waiting["state"] != "awaiting_region_review":
                    raise RuntimeError(f"detector_state_{waiting['state']}")
                regions = client.get(f"/api/v1/pages/{page_id}/regions").json()
                if not regions["regions"]:
                    raise RuntimeError("craft_produced_no_review_regions")
                craft_review_region_count = len(regions["regions"])
                manual_review_correction_applied = False
                if review_regions and craft_review_region_count < len(review_regions):
                    corrected = client.put(
                        f"/api/v1/pages/{page_id}/regions",
                        json={"revision": regions["revision"], "regions": review_regions},
                        headers={"X-CSRF-Token": csrf},
                    )
                    if corrected.status_code != 200:
                        raise RuntimeError(f"review_correction_http_{corrected.status_code}")
                    regions = corrected.json()
                    manual_review_correction_applied = True
                if arguments.compose_page and len(regions["regions"]) < 2:
                    raise RuntimeError("craft_full_page_regions_insufficient")
                resumed = client.post(
                    f"/api/v1/pages/{page_id}/regions/confirm",
                    json={
                        "revision": regions["revision"],
                        "job_id": job_id,
                        "job_revision": waiting["revision"],
                    },
                    headers={"X-CSRF-Token": csrf},
                )
                if resumed.status_code != 200:
                    raise RuntimeError(f"region_confirm_http_{resumed.status_code}")
                WorkerService(
                    client.app.state.jobs,
                    worker_id="http-verify-recognizer",
                    lease_seconds=90,
                    handlers={"page_recognition": handler},
                ).run_once()
                completed = client.get(f"/api/v1/jobs/{job_id}").json()
                if completed["state"] not in {"completed", "partial"}:
                    raise RuntimeError(f"recognizer_state_{completed['state']}")
                connection = client.app.state.database.connect()
                try:
                    raw = connection.execute(
                        """SELECT p.raw_text,p.is_partial,r.pipeline_manifest_sha256,r.craft_detector_version,
                                  r.trocr_model_version,r.rslora_adapter_version,r.device,r.dtype
                           FROM page_raw_results p
                           JOIN recognition_runs r ON r.id=p.recognition_run_id
                           WHERE r.job_id=?""",
                        (job_id,),
                    ).fetchone()
                    counts = connection.execute(
                        """SELECT
                             (SELECT COUNT(*) FROM recognition_line_crops WHERE recognition_run_id=r.id),
                             (SELECT COUNT(*) FROM recognition_line_results WHERE recognition_run_id=r.id)
                           FROM recognition_runs r WHERE r.job_id=?""",
                        (job_id,),
                    ).fetchone()
                finally:
                    connection.close()
                if raw is None:
                    raise RuntimeError("page_raw_result_missing")
                if counts is None or counts[0] != len(regions["regions"]) or counts[1] != len(regions["regions"]):
                    raise RuntimeError("line_result_persistence_mismatch")
                if any(raw[field] is None for field in (
                    "pipeline_manifest_sha256",
                    "craft_detector_version",
                    "trocr_model_version",
                    "rslora_adapter_version",
                    "device",
                    "dtype",
                )):
                    raise RuntimeError("recognition_run_manifest_evidence_missing")
        except (OSError, RuntimeError) as error:
            print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
            return 1
        finally:
            main_module.settings = original_settings
            _remove_temporary_root(root)

        print(
            json.dumps(
                {
                    "status": "ready",
                    "job_state": completed["state"],
                    "job_stage": completed["stage"],
                    "processed_count": completed["processed_count"],
                    "total_count": completed["total_count"],
                    "craft_review_region_count": craft_review_region_count,
                    "confirmed_region_count": len(regions["regions"]),
                    "manual_review_correction_applied": manual_review_correction_applied,
                    "composed_real_page": arguments.compose_page,
                    "line_crop_count": counts[0],
                    "line_result_count": counts[1],
                    "model_manifest_evidence": True,
                    "is_partial": bool(raw["is_partial"]),
                    "raw_text_sha256": hashlib.sha256(str(raw["raw_text"]).encode("utf-8")).hexdigest(),
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
