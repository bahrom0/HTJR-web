from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from PIL import Image

from app.core.database import Database
from app.core.storage import FileStorage
from app.ml.craft_runtime import CraftDetection
from app.ml.trocr_runtime import TrocrGeneration, TrocrReadinessEvidence, TrocrRuntimeError
from app.repositories.jobs import JobRepository
from app.repositories.recognition import RecognitionRepository
from app.repositories.regions import RegionRepository
from app.services.jobs import WorkerService
from app.worker.main import run_page_recognition


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _image_bytes() -> bytes:
    image = Image.new("RGB", (240, 120), "white")
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def _store_image(storage: FileStorage, payload: bytes):
    staged = storage.stage(io.BytesIO(payload))
    return storage.commit(staged)


def _seed_page(database: Database, storage: FileStorage) -> tuple[str, str]:
    owner, document_id, page_id = str(uuid4()), str(uuid4()), str(uuid4())
    source_id, prepared_id = str(uuid4()), str(uuid4())
    payload = _image_bytes()
    source = _store_image(storage, payload)
    prepared = _store_image(storage, payload)
    now = _now()
    with database.transaction(immediate=True) as connection:
        connection.execute(
            """INSERT INTO access_sessions(id,token_hash,csrf_hash,created_at,expires_at,last_seen_at)
               VALUES (?,?,?,?,?,?)""",
            (owner, f"token-{owner}".encode(), f"csrf-{owner}".encode(), now, (datetime.now(UTC) + timedelta(hours=1)).isoformat(), now),
        )
        connection.execute(
            "INSERT INTO documents(id,owner_session_id,title,created_at,updated_at) VALUES (?,?,?,?,?)",
            (document_id, owner, "Pipeline test", now, now),
        )
        connection.execute(
            """INSERT INTO assets(
                   id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,committed_at,
                   kind,width,height)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (source_id, owner, document_id, source.storage_key, source.sha256, source.byte_size, "image/png", "committed", now, now, "original", 240, 120),
        )
        connection.execute(
            """INSERT INTO assets(
                   id,owner_session_id,document_id,storage_key,sha256,byte_size,media_type,state,created_at,committed_at,
                   kind,width,height,parent_asset_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (prepared_id, owner, document_id, prepared.storage_key, prepared.sha256, prepared.byte_size, "image/png", "committed", now, now, "prepared", 240, 120, source_id),
        )
        connection.execute(
            """INSERT INTO pages(
                   id,document_id,source_asset_id,page_index,created_at,updated_at,prepared_asset_id,
                   preprocessing_recipe_hash,preparation_confirmed_recipe_hash)
               VALUES (?,?,?,?,?,?,?,?,?)""",
            (page_id, document_id, source_id, 0, now, now, prepared_id, "a" * 64, "a" * 64),
        )
    return owner, page_id


class _FakeCraftRuntime:
    def close(self) -> None:
        return None

    def detect(self, image: Image.Image) -> CraftDetection:
        score_map = np.zeros((30, 60), dtype=np.float32)
        score_map[2:8, 2:45] = 0.95
        score_map[16:23, 2:45] = 0.92
        return CraftDetection(
            detector_version="fake-craft-v1",
            thresholds_version="fake-thresholds-v1",
            width=image.width,
            height=image.height,
            text_score_map=score_map,
            link_score_map=np.zeros_like(score_map),
            boxes=((8.0, 8.0, 190.0, 34.0), (8.0, 65.0, 190.0, 96.0)),
            polygons=(
                ((8.0, 8.0), (190.0, 8.0), (190.0, 34.0), (8.0, 34.0)),
                ((8.0, 65.0), (190.0, 65.0), (190.0, 96.0), (8.0, 96.0)),
            ),
            scores=(0.95, 0.92),
            duration_ms=3,
            warmup_ms=1,
        )


class _FakeTrocrRuntime:
    def __init__(self, *, fail_line: int | None = None, crash_line: int | None = None) -> None:
        self.evidence = TrocrReadinessEvidence(
            model_version="fake-trocr-v1",
            adapter_version="fake-rslora-v1",
            manifest_sha256="c" * 64,
            device="cpu",
            dtype="float32",
            adapter_state_parameter_count=10,
            lora_tensor_count=2,
            nonzero_lora_parameter_count=8,
            warmup_duration_ms=1,
            warmup_generated_token_count=2,
        )
        self.calls = 0
        self.fail_line = fail_line
        self.crash_line = crash_line

    def warmup(self) -> TrocrReadinessEvidence:
        return self.evidence

    def close(self) -> None:
        return None

    def recognize(self, _image: Image.Image, *, num_beams: int, max_new_tokens: int) -> TrocrGeneration:
        self.calls += 1
        if self.crash_line == self.calls:
            raise RuntimeError("simulated_worker_crash")
        if self.fail_line == self.calls:
            raise TrocrRuntimeError("trocr_generate_failed")
        return TrocrGeneration(
            text=f"raw-line-{self.calls}",
            duration_ms=4,
            generated_token_count=5,
            decoding_steps=4,
            mean_token_log_probability=-0.25,
        )


def _service(
    database: Database,
    storage: FileStorage,
    craft: _FakeCraftRuntime,
    trocr: _FakeTrocrRuntime,
    *,
    worker_id: str,
) -> WorkerService:
    repository = JobRepository(database)
    return WorkerService(
        repository,
        worker_id=worker_id,
        lease_seconds=30,
        handlers={
            "page_recognition": lambda context: run_page_recognition(
                context,
                database=database,
                storage=storage,
                models_root=storage.root / "models-without-weights",
                craft_runtime=craft,  # type: ignore[arg-type]
                trocr_runtime=trocr,  # type: ignore[arg-type]
            )
        },
    )


@pytest.fixture
def pipeline(tmp_path: Path) -> tuple[Database, FileStorage, JobRepository, str, str]:
    database = Database(tmp_path / "pipeline.sqlite3")
    database.migrate()
    storage = FileStorage(tmp_path / "assets")
    owner, page_id = _seed_page(database, storage)
    return database, storage, JobRepository(database), owner, page_id


def _enqueue_and_detect(pipeline) -> tuple[object, str]:
    database, storage, repository, owner, page_id = pipeline
    job, duplicate = repository.enqueue(owner, page_id, "pipeline-detect-key-001", priority=0, capacity=4, max_attempts=3)
    assert duplicate is False
    assert _service(database, storage, _FakeCraftRuntime(), _FakeTrocrRuntime(), worker_id="detector").run_once() is True
    waiting = repository.get(owner, job.id)
    assert waiting.state == "awaiting_region_review"
    assert waiting.stage == "awaiting_region_review"
    with database.connect() as connection:
        page_revision = int(connection.execute("SELECT revision FROM pages WHERE id=?", (page_id,)).fetchone()[0])
        output = connection.execute(
            "SELECT recognition_run_id,thresholds_json,output_json FROM craft_detector_outputs WHERE job_id=?", (job.id,)
        ).fetchone()
    assert output is not None
    assert json.loads(output["thresholds_json"])["values"]["text"] == 0.7
    assert json.loads(output["output_json"])["grouping"]["line_candidate_count"] == 2
    return waiting, str(page_revision)


def test_durable_pipeline_pauses_for_review_then_assembles_raw_page(pipeline) -> None:
    database, storage, repository, owner, page_id = pipeline
    waiting, page_revision = _enqueue_and_detect(pipeline)
    _, queued = repository.confirm_regions_and_resume(
        owner,
        page_id,
        expected_page_revision=int(page_revision),
        job_id=waiting.id,
        expected_job_revision=waiting.revision,
    )
    assert queued.state == "queued" and queued.stage == "recognizing_lines"
    trocr = _FakeTrocrRuntime()
    assert _service(database, storage, _FakeCraftRuntime(), trocr, worker_id="recognizer").run_once() is True
    completed = repository.get(owner, waiting.id)
    assert completed.state == "completed"
    assert (completed.processed_count, completed.total_count) == (2, 2)
    assert trocr.calls == 2
    with database.connect() as connection:
        assembled = connection.execute("SELECT raw_text,is_partial FROM page_raw_results").fetchone()
        run = connection.execute("SELECT prepared_asset_sha256,trocr_model_version,rslora_adapter_version FROM recognition_runs").fetchone()
        crop_count = connection.execute("SELECT COUNT(*) FROM recognition_line_crops").fetchone()[0]
    assert assembled["raw_text"] == "raw-line-1\nraw-line-2"
    assert assembled["is_partial"] == 0
    assert run["prepared_asset_sha256"] is not None
    assert (run["trocr_model_version"], run["rslora_adapter_version"]) == ("fake-trocr-v1", "fake-rslora-v1")
    assert crop_count == 2


def test_partial_line_is_saved_with_placeholder_and_only_failed_line_retries(pipeline) -> None:
    database, storage, repository, owner, page_id = pipeline
    waiting, page_revision = _enqueue_and_detect(pipeline)
    repository.confirm_regions_and_resume(
        owner,
        page_id,
        expected_page_revision=int(page_revision),
        job_id=waiting.id,
        expected_job_revision=waiting.revision,
    )
    failing = _FakeTrocrRuntime(fail_line=2)
    _service(database, storage, _FakeCraftRuntime(), failing, worker_id="recognizer").run_once()
    partial = repository.get(owner, waiting.id)
    assert partial.state == "partial"
    with database.connect() as connection:
        raw = connection.execute("SELECT raw_text,is_partial FROM page_raw_results").fetchone()
        run_id = connection.execute("SELECT id FROM recognition_runs WHERE job_id=? AND finished_at IS NULL", (waiting.id,)).fetchone()[0]
    assert raw["is_partial"] == 1
    assert "[Не распознано: строка 2]" in raw["raw_text"]
    repository.retry(owner, waiting.id)
    recovered = _FakeTrocrRuntime()
    _service(database, storage, _FakeCraftRuntime(), recovered, worker_id="retry-worker").run_once()
    assert repository.get(owner, waiting.id).state == "completed"
    assert recovered.calls == 1
    with database.connect() as connection:
        raw = connection.execute("SELECT raw_text,is_partial FROM page_raw_results").fetchone()
        resumed_run_id = connection.execute("SELECT id FROM recognition_runs WHERE job_id=?", (waiting.id,)).fetchone()[0]
    assert raw["raw_text"] == "raw-line-1\nraw-line-1"
    assert raw["is_partial"] == 0
    assert resumed_run_id == run_id


def test_worker_crash_preserves_completed_lines_and_active_run_for_restart(pipeline) -> None:
    database, storage, repository, owner, page_id = pipeline
    waiting, page_revision = _enqueue_and_detect(pipeline)
    repository.confirm_regions_and_resume(
        owner,
        page_id,
        expected_page_revision=int(page_revision),
        job_id=waiting.id,
        expected_job_revision=waiting.revision,
    )
    crashing = _FakeTrocrRuntime(crash_line=2)
    _service(database, storage, _FakeCraftRuntime(), crashing, worker_id="crashing-worker").run_once()
    failed = repository.get(owner, waiting.id)
    assert failed.state == "failed_retryable"
    with database.connect() as connection:
        run_id = connection.execute("SELECT id FROM recognition_runs WHERE job_id=? AND finished_at IS NULL", (waiting.id,)).fetchone()[0]
        completed_count = connection.execute("SELECT COUNT(*) FROM recognition_line_results WHERE state='completed'").fetchone()[0]
    assert completed_count == 1
    repository.retry(owner, waiting.id)
    resumed = _FakeTrocrRuntime()
    _service(database, storage, _FakeCraftRuntime(), resumed, worker_id="restarted-worker").run_once()
    assert repository.get(owner, waiting.id).state == "completed"
    assert resumed.calls == 1
    with database.connect() as connection:
        resumed_run_id = connection.execute("SELECT id FROM recognition_runs WHERE job_id=?", (waiting.id,)).fetchone()[0]
    assert resumed_run_id == run_id


def test_confirmed_regions_create_padded_immutable_line_crops(pipeline) -> None:
    database, storage, repository, owner, page_id = pipeline
    waiting, page_revision = _enqueue_and_detect(pipeline)
    repository.confirm_regions_and_resume(
        owner,
        page_id,
        expected_page_revision=int(page_revision),
        job_id=waiting.id,
        expected_job_revision=waiting.revision,
    )
    with database.connect() as connection:
        run_id = str(connection.execute("SELECT id FROM recognition_runs WHERE job_id=?", (waiting.id,)).fetchone()[0])
    recognition = RecognitionRepository(database, storage)
    snapshot_regions = recognition.run_regions(owner, run_id)
    assert len(snapshot_regions) == 2

    prepared_key = recognition.prepared_storage_key(owner, run_id)
    with Image.open(storage.resolve(prepared_key)) as prepared:
        crop = recognition.crop_for_region(
            owner,
            run_id,
            snapshot_regions[0],
            prepared,
            padding_fraction=0.08,
        )
    # CRAFT's first fake polygon is x=8..190 in a 240px page.  Padding is
    # normalized to page geometry, so the immutable crop is wider than the
    # unpadded 182px detector box and safely bounded by the source image.
    assert 182 < crop.width <= 240
    assert 26 < crop.height <= 120

    current_revision, _, current_regions = RegionRepository(database).list(owner, page_id)
    RegionRepository(database).replace(
        owner,
        page_id,
        current_revision,
        [
            {
                "polygon": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.2},
                    {"x": 0.1, "y": 0.2},
                ],
                "reading_order": 0,
                "source": "manual",
                "flags": [],
            }
        ],
    )
    # Editing the mutable page regions later never rewrites the run snapshot
    # or the already committed crop.
    assert recognition.run_regions(owner, run_id) == snapshot_regions
    assert storage.resolve(crop.storage_key).is_file()
    assert len(current_regions) == 2


def test_manual_fallback_replaces_only_failed_raw_line_and_closes_partial_job(pipeline) -> None:
    database, storage, repository, owner, page_id = pipeline
    waiting, page_revision = _enqueue_and_detect(pipeline)
    repository.confirm_regions_and_resume(
        owner,
        page_id,
        expected_page_revision=int(page_revision),
        job_id=waiting.id,
        expected_job_revision=waiting.revision,
    )
    _service(database, storage, _FakeCraftRuntime(), _FakeTrocrRuntime(fail_line=2), worker_id="recognizer").run_once()
    assert repository.get(owner, waiting.id).state == "partial"
    with database.connect() as connection:
        run_id = str(connection.execute("SELECT id FROM recognition_runs WHERE job_id=?", (waiting.id,)).fetchone()[0])
    recognition = RecognitionRepository(database, storage)
    failed_region = next(
        region
        for region in recognition.run_regions(owner, run_id)
        if recognition.latest_results(owner, run_id)[region.id].state == "failed_retryable"
    )

    returned_run_id, remains_partial = recognition.record_manual_fallback(
        owner,
        waiting.id,
        failed_region.id,
        raw_text="manual-raw-line",
    )

    assert returned_run_id == run_id
    assert remains_partial is False
    completed = repository.complete_manual_fallback(owner, waiting.id, run_id)
    assert completed.state == "completed"
    with database.connect() as connection:
        raw = connection.execute("SELECT raw_text,is_partial FROM page_raw_results WHERE recognition_run_id=?", (run_id,)).fetchone()
        latest = connection.execute(
            """SELECT generation_json FROM recognition_line_results
               WHERE recognition_run_id=? AND run_region_id=? ORDER BY line_attempt DESC LIMIT 1""",
            (run_id, failed_region.id),
        ).fetchone()
    assert raw["raw_text"] == "raw-line-1\nmanual-raw-line"
    assert raw["is_partial"] == 0
    assert json.loads(latest["generation_json"]) == {"source": "manual_fallback"}
