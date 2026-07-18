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
    job_queue_capacity = int(values.get("HTR_JOB_QUEUE_CAPACITY", "32"))
    job_max_attempts = int(values.get("HTR_JOB_MAX_ATTEMPTS", "3"))
    if worker_lease_seconds <= heartbeat:
        raise ValueError("HTR_WORKER_LEASE_SECONDS must exceed the heartbeat interval")
    if worker_poll_seconds <= 0:
        raise ValueError("HTR_WORKER_POLL_SECONDS must be positive")
    if job_queue_capacity < 1 or job_max_attempts < 1:
        raise ValueError("Job capacity and attempts must be positive")
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
    )


settings = read_settings()
