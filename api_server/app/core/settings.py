from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    host: str
    port: int
    worker_heartbeat_seconds: int
    database_path: Path
    storage_root: Path
    access_code_ttl_seconds: int
    session_ttl_seconds: int
    access_attempt_limit: int
    access_attempt_window_seconds: int
    cookie_name: str
    cookie_secure: bool
    upload_max_bytes: int
    image_max_pixels: int
    image_max_dimension: int
    prepared_max_edge: int
    preview_max_edge: int
    job_queue_capacity: int
    job_max_attempts: int
    worker_lease_seconds: int
    worker_poll_seconds: float
    sse_heartbeat_seconds: float
    sse_poll_seconds: float
    ml_device: str
    craft_max_edge: int
    line_crop_padding: float
    trocr_num_beams: int
    trocr_max_new_tokens: int


def read_settings(source: dict[str, str] | None = None) -> Settings:
    values = environ if source is None else source
    port = int(values.get("HTR_API_PORT", "8000"))
    heartbeat = int(values.get("HTR_WORKER_HEARTBEAT_SECONDS", "30"))
    if not 1 <= port <= 65535:
        raise ValueError("HTR_API_PORT must be between 1 and 65535")
    if heartbeat < 1:
        raise ValueError("HTR_WORKER_HEARTBEAT_SECONDS must be positive")
    worker_lease_seconds = int(values.get("HTR_WORKER_LEASE_SECONDS", "90"))
    worker_poll_seconds = float(values.get("HTR_WORKER_POLL_SECONDS", "1"))
    sse_heartbeat_seconds = float(values.get("HTR_SSE_HEARTBEAT_SECONDS", "15"))
    sse_poll_seconds = float(values.get("HTR_SSE_POLL_SECONDS", "0.5"))
    job_queue_capacity = int(values.get("HTR_JOB_QUEUE_CAPACITY", "32"))
    job_max_attempts = int(values.get("HTR_JOB_MAX_ATTEMPTS", "3"))
    ml_device = values.get("HTR_ML_DEVICE", "auto").lower()
    craft_max_edge = int(values.get("HTR_CRAFT_MAX_EDGE", "2048"))
    line_crop_padding = float(values.get("HTR_LINE_CROP_PADDING", "0.08"))
    trocr_num_beams = int(values.get("HTR_TROCR_NUM_BEAMS", "1"))
    trocr_max_new_tokens = int(values.get("HTR_TROCR_MAX_NEW_TOKENS", "128"))
    if worker_lease_seconds <= heartbeat:
        raise ValueError("HTR_WORKER_LEASE_SECONDS must exceed the heartbeat interval")
    if worker_poll_seconds <= 0:
        raise ValueError("HTR_WORKER_POLL_SECONDS must be positive")
    if sse_heartbeat_seconds <= 0 or sse_poll_seconds <= 0:
        raise ValueError("SSE heartbeat and poll intervals must be positive")
    if sse_poll_seconds > sse_heartbeat_seconds:
        raise ValueError("HTR_SSE_POLL_SECONDS must not exceed HTR_SSE_HEARTBEAT_SECONDS")
    if job_queue_capacity < 1 or job_max_attempts < 1:
        raise ValueError("Job capacity and attempts must be positive")
    if ml_device not in {"auto", "cpu", "cuda"}:
        raise ValueError("HTR_ML_DEVICE must be auto, cpu, or cuda")
    if not 256 <= craft_max_edge <= 4096:
        raise ValueError("HTR_CRAFT_MAX_EDGE must be between 256 and 4096")
    if not 0 <= line_crop_padding <= 0.25:
        raise ValueError("HTR_LINE_CROP_PADDING must be between 0 and 0.25")
    if not 1 <= trocr_num_beams <= 4 or not 1 <= trocr_max_new_tokens <= 256:
        raise ValueError("TrOCR generation settings are outside safe bounds")
    project_root = Path(__file__).resolve().parents[2]
    data_root = Path(values.get("HTR_DATA_ROOT", str(project_root / "data"))).resolve()
    environment = values.get("HTR_API_ENV", "development")
    return Settings(
        environment,
        values.get("HTR_API_HOST", "127.0.0.1"),
        port,
        heartbeat,
        Path(values.get("HTR_DATABASE_PATH", str(data_root / "studio.sqlite3"))).resolve(),
        Path(values.get("HTR_STORAGE_ROOT", str(data_root / "assets"))).resolve(),
        int(values.get("HTR_ACCESS_CODE_TTL_SECONDS", "900")),
        int(values.get("HTR_SESSION_TTL_SECONDS", "28800")),
        int(values.get("HTR_ACCESS_ATTEMPT_LIMIT", "5")),
        int(values.get("HTR_ACCESS_ATTEMPT_WINDOW_SECONDS", "300")),
        values.get("HTR_SESSION_COOKIE_NAME", "htr_session"),
        values.get("HTR_COOKIE_SECURE", "true" if environment == "production" else "false").lower() == "true",
        int(values.get("HTR_UPLOAD_MAX_BYTES", str(25 * 1024 * 1024))),
        int(values.get("HTR_IMAGE_MAX_PIXELS", "40000000")),
        int(values.get("HTR_IMAGE_MAX_DIMENSION", "12000")),
        int(values.get("HTR_PREPARED_MAX_EDGE", "4096")),
        int(values.get("HTR_PREVIEW_MAX_EDGE", "1600")),
        job_queue_capacity,
        job_max_attempts,
        worker_lease_seconds,
        worker_poll_seconds,
        sse_heartbeat_seconds,
        sse_poll_seconds,
        ml_device,
        craft_max_edge,
        line_crop_padding,
        trocr_num_beams,
        trocr_max_new_tokens,
    )


settings = read_settings()
