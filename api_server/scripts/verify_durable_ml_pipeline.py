from __future__ import annotations

"""Run a local prepared page through the real persisted CRAFT -> review -> TrOCR pipeline."""

import argparse
import hashlib
import io
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from PIL import Image

from app.core.database import Database
from app.core.storage import FileStorage
from app.repositories.jobs import JobRepository
from app.services.jobs import WorkerService
from app.worker.main import _run_phase_subprocess


def _seed_prepared_page(database: Database, storage: FileStorage, image_path: Path) -> tuple[str, str]:
    owner, document_id, page_id = str(uuid4()), str(uuid4()), str(uuid4())
    source_id, prepared_id = str(uuid4()), str(uuid4())
    payload = image_path.read_bytes()
    source = storage.commit(storage.stage(io.BytesIO(payload)))
    prepared = storage.commit(storage.stage(io.BytesIO(payload)))
    with Image.open(io.BytesIO(payload)) as source_image:
        width, height = source_image.size
    now = datetime.now(UTC).isoformat()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO access_sessions(id,token_hash,csrf_hash,created_at,expires_at,last_seen_at)
               VALUES (?,?,?,?,?,?)""",
            (owner, f"token-{owner}".encode(), f"csrf-{owner}".encode(), now, (datetime.now(UTC) + timedelta(hours=1)).isoformat(), now),
        )
        connection.execute(
            "INSERT INTO documents(id,owner_session_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
            (document_id, owner, "Runtime verification", now, now),
        )
        connection.execute(
            """INSERT INTO assets(
                   id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,committed_at,kind,width,height)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, owner, document_id, source.storage_key, source.sha256, source.byte_size, "image/png", "committed", now, now, "original", width, height),
        )
        connection.execute(
            """INSERT INTO assets(
                   id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,committed_at,kind,width,height,parent_asset_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (prepared_id, owner, document_id, prepared.storage_key, prepared.sha256, prepared.byte_size, "image/png", "committed", now, now, "prepared", width, height, source_id),
        )
        connection.execute(
            """INSERT INTO pages(
                   id,document_id,source_asset_id,page_index,created_at,updated_at,prepared_asset_id,
                   preprocessing_recipe_hash,preparation_confirmed_recipe_hash)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (page_id, document_id, source_id, 0, now, now, prepared_id, "a" * 64, "a" * 64),
        )
    return owner, page_id


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    arguments = parser.parse_args()
    if not arguments.image.is_file():
        parser.error("--image must be a readable local image")

    with tempfile.TemporaryDirectory(prefix="tajik-htr-runtime-") as temporary:
        root = Path(temporary)
        database = Database(root / "studio.sqlite3")
        database.migrate()
        storage = FileStorage(root / "assets")
        owner, page_id = _seed_prepared_page(database, storage, arguments.image)
        repository = JobRepository(database)
        job, _ = repository.enqueue(owner, page_id, "durable-runtime-verification-001", priority=0, capacity=1, max_attempts=3)
        models_root = Path(__file__).resolve().parents[1] / "models"
        try:
            handler = lambda context: _run_phase_subprocess(
                context,
                database=database,
                storage=storage,
                models_root=models_root,
                device=arguments.device,
            )
            WorkerService(repository, worker_id="verify-detector", lease_seconds=90, handlers={"page_recognition": handler}).run_once()
            waiting = repository.get(owner, job.id)
            if waiting.state != "awaiting_region_review":
                raise RuntimeError(f"detector_phase_state_{waiting.state}")
            connection = database.connect()
            try:
                revision = int(connection.execute("SELECT revision FROM pages WHERE id=?", (page_id,)).fetchone()[0])
                run_id = str(connection.execute("SELECT id FROM recognition_runs WHERE job_id=? AND finished_at IS NULL", (job.id,)).fetchone()[0])
            finally:
                connection.close()
            repository.confirm_regions_and_resume(
                owner,
                page_id,
                expected_page_revision=revision,
                job_id=job.id,
                expected_job_revision=waiting.revision,
            )
            WorkerService(repository, worker_id="verify-recognizer", lease_seconds=90, handlers={"page_recognition": handler}).run_once()
            completed = repository.get(owner, job.id)
            if completed.state not in {"completed", "partial"}:
                raise RuntimeError(f"recognition_phase_state_{completed.state}")
            connection = database.connect()
            try:
                raw = connection.execute(
                    "SELECT raw_text,is_partial FROM page_raw_results WHERE recognition_run_id=?", (run_id,)
                ).fetchone()
                crops = connection.execute("SELECT COUNT(*) FROM recognition_line_crops WHERE recognition_run_id=?", (run_id,)).fetchone()[0]
                lines = connection.execute("SELECT COUNT(*) FROM recognition_line_results WHERE recognition_run_id=?", (run_id,)).fetchone()[0]
            finally:
                connection.close()
        except (OSError, RuntimeError) as error:
            print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
            return 1

        print(
            json.dumps(
                {
                    "status": "ready",
                    "job_state": completed.state,
                    "job_stage": completed.stage,
                    "processed_count": completed.processed_count,
                    "total_count": completed.total_count,
                    "recognition_run_id": run_id,
                    "phase_process_isolation": True,
                    "line_crop_count": crops,
                    "line_result_count": lines,
                    "is_partial": bool(raw["is_partial"]),
                    "raw_text_sha256": hashlib.sha256(str(raw["raw_text"]).encode("utf-8")).hexdigest(),
                },
                sort_keys=True,
            )
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
