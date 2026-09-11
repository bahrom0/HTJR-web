from __future__ import annotations

from dataclasses import dataclass
from os import environ
from pathlib import Path
import tomllib


@dataclass(frozen=True, slots=True)
class Settings:
    environment: str
    host: str
    port: int
    worker_heartbeat_seconds: int
    database_path: Path
    storage_root: Path
    session_ttl_seconds: int
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
    craft_enabled: bool
    craft_max_edge: int
    kraken_endpoint: str
    kraken_timeout_seconds: float
    line_crop_padding: float
    trocr_num_beams: int
    trocr_max_new_tokens: int
    trocr_batch_size: int
    trocr_adapter_mode: str
    ocr_provider: str
    gemini_mode: str
    gemini_model: str
    openrouter_api_key: str | None
    gemini_timeout_seconds: float
    gemini_thinking_level: str
    gemini_max_output_tokens: int
    gemini_max_page_regions: int
    account_attempt_limit: int
    account_attempt_window_seconds: int


def _read_ml_config(config_path: Path) -> tuple[bool, bool, int, str, float, str, str, str, str, float, str, int, int]:
    try:
        with config_path.open("rb") as source:
            raw = tomllib.load(source)
    except FileNotFoundError:
        return (
            True,
            True,
            4,
            "http://127.0.0.1:8011",
            180.0,
            "none",
            "trocr",
            "page",
            "google/gemini-3.8-flash:floor",
            120.0,
            "low",
            4096,
            200,
        )
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ValueError(f"Invalid project config: {config_path}") from error

    ml = raw.get("ml", {})
    if not isinstance(ml, dict):
        raise ValueError("[ml] must be a TOML table")
    cuda_enabled = ml.get("CUDA", True)
    craft_enabled = ml.get("CRAFT", True)
    batch_size = ml.get("trocr_batch_size", 4)
    adapter_mode = ml.get("trocr_adapter_mode", "none")
    kraken_endpoint = ml.get("kraken_endpoint", "http://127.0.0.1:8011")
    kraken_timeout_seconds = ml.get("kraken_timeout_seconds", 180.0)
    ocr_provider = ml.get("ocr_provider", "trocr")
    gemini_mode = ml.get("gemini_mode", "page")
    gemini_model = ml.get("gemini_model", "google/gemini-3.8-flash:floor")
    gemini_timeout_seconds = ml.get("gemini_timeout_seconds", 120.0)
    gemini_thinking_level = ml.get("gemini_thinking_level", "low")
    gemini_max_output_tokens = ml.get("gemini_max_output_tokens", 4096)
    gemini_max_page_regions = ml.get("gemini_max_page_regions", 200)
    if not isinstance(cuda_enabled, bool):
        raise ValueError("ml.CUDA must be true or false")
    if not isinstance(craft_enabled, bool):
        raise ValueError("ml.CRAFT must be true or false")
    if not isinstance(batch_size, int) or not 1 <= batch_size <= 16:
        raise ValueError("ml.trocr_batch_size must be between 1 and 16")
    if not isinstance(adapter_mode, str) or adapter_mode.lower() not in {"none", "rslora"}:
        raise ValueError("ml.trocr_adapter_mode must be none or rslora")
    if not isinstance(ocr_provider, str) or ocr_provider.lower() not in {"trocr", "gemini"}:
        raise ValueError("ml.ocr_provider must be trocr or gemini")
    if not isinstance(gemini_mode, str) or gemini_mode.lower() not in {"page", "kraken"}:
        raise ValueError("ml.gemini_mode must be page or kraken")
    if not isinstance(gemini_model, str) or not gemini_model.strip():
        raise ValueError("ml.gemini_model must be a non-empty string")
    if not isinstance(gemini_thinking_level, str) or gemini_thinking_level.lower() not in {"low", "medium", "high"}:
        raise ValueError("ml.gemini_thinking_level must be low, medium, or high")
    if not isinstance(gemini_max_output_tokens, int) or not 128 <= gemini_max_output_tokens <= 65536:
        raise ValueError("ml.gemini_max_output_tokens must be between 128 and 65536")
    if not isinstance(gemini_max_page_regions, int) or not 1 <= gemini_max_page_regions <= 1000:
        raise ValueError("ml.gemini_max_page_regions must be between 1 and 1000")
    if not isinstance(kraken_endpoint, str) or not kraken_endpoint.startswith(("http://127.0.0.1:", "http://localhost:")):
        raise ValueError("ml.kraken_endpoint must be a loopback HTTP URL")
    if (
        not isinstance(kraken_timeout_seconds, (int, float))
        or isinstance(kraken_timeout_seconds, bool)
        or not 1 <= kraken_timeout_seconds <= 900
    ):
        raise ValueError("ml.kraken_timeout_seconds must be between 1 and 900")
    if (
        not isinstance(gemini_timeout_seconds, (int, float))
        or isinstance(gemini_timeout_seconds, bool)
        or not 1 <= gemini_timeout_seconds <= 900
    ):
        raise ValueError("ml.gemini_timeout_seconds must be between 1 and 900")
    return (
        cuda_enabled,
        craft_enabled,
        batch_size,
        kraken_endpoint,
        float(kraken_timeout_seconds),
        adapter_mode.lower(),
        ocr_provider.lower(),
        gemini_mode.lower(),
        gemini_model.strip(),
        float(gemini_timeout_seconds),
        gemini_thinking_level.lower(),
        gemini_max_output_tokens,
        gemini_max_page_regions,
    )


def read_settings(source: dict[str, str] | None = None, *, config_path: Path | None = None) -> Settings:
    values = environ if source is None else source
    project_root = Path(__file__).resolve().parents[2]
    (
        cuda_enabled,
        craft_enabled,
        configured_batch_size,
        kraken_endpoint,
        kraken_timeout_seconds,
        configured_adapter_mode,
        configured_ocr_provider,
        configured_gemini_mode,
        configured_gemini_model,
        configured_gemini_timeout_seconds,
        configured_gemini_thinking_level,
        configured_gemini_max_output_tokens,
        configured_gemini_max_page_regions,
    ) = _read_ml_config(config_path or project_root / "config.toml")
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
    ml_device = values.get("HTR_ML_DEVICE", "auto" if cuda_enabled else "cpu").lower()
    craft_max_edge = int(values.get("HTR_CRAFT_MAX_EDGE", "2048"))
    line_crop_padding = float(values.get("HTR_LINE_CROP_PADDING", "0.08"))
    trocr_num_beams = int(values.get("HTR_TROCR_NUM_BEAMS", "1"))
    trocr_max_new_tokens = int(values.get("HTR_TROCR_MAX_NEW_TOKENS", "128"))
    trocr_batch_size = int(values.get("HTR_TROCR_BATCH_SIZE", str(configured_batch_size)))
    trocr_adapter_mode = values.get("HTR_TROCR_ADAPTER_MODE", configured_adapter_mode).lower()
    ocr_provider = values.get("HTR_OCR_PROVIDER", configured_ocr_provider).lower()
    gemini_mode = values.get("HTR_GEMINI_MODE", configured_gemini_mode).lower()
    gemini_model = values.get("HTR_GEMINI_MODEL", configured_gemini_model).strip()
    gemini_timeout_seconds = float(
        values.get("HTR_GEMINI_TIMEOUT_SECONDS", str(configured_gemini_timeout_seconds))
    )
    gemini_thinking_level = values.get(
        "HTR_GEMINI_THINKING_LEVEL", configured_gemini_thinking_level
    ).lower()
    gemini_max_output_tokens = int(
        values.get("HTR_GEMINI_MAX_OUTPUT_TOKENS", str(configured_gemini_max_output_tokens))
    )
    gemini_max_page_regions = int(
        values.get("HTR_GEMINI_MAX_PAGE_REGIONS", str(configured_gemini_max_page_regions))
    )
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
    if not 1 <= trocr_batch_size <= 16:
        raise ValueError("HTR_TROCR_BATCH_SIZE must be between 1 and 16")
    if trocr_adapter_mode not in {"none", "rslora"}:
        raise ValueError("HTR_TROCR_ADAPTER_MODE must be none or rslora")
    if ocr_provider == "gemini":
        # The cloud path must never initialize the local TrOCR/rsLoRA stack.
        trocr_adapter_mode = "none"
        trocr_batch_size = 1
    if ocr_provider not in {"trocr", "gemini"}:
        raise ValueError("HTR_OCR_PROVIDER must be trocr or gemini")
    if gemini_mode not in {"page", "kraken"}:
        raise ValueError("HTR_GEMINI_MODE must be page or kraken")
    if not gemini_model:
        raise ValueError("HTR_GEMINI_MODEL must be a non-empty string")
    if gemini_thinking_level not in {"low", "medium", "high"}:
        raise ValueError("HTR_GEMINI_THINKING_LEVEL must be low, medium, or high")
    if not 1 <= gemini_timeout_seconds <= 900:
        raise ValueError("HTR_GEMINI_TIMEOUT_SECONDS must be between 1 and 900")
    if not 128 <= gemini_max_output_tokens <= 65536:
        raise ValueError("HTR_GEMINI_MAX_OUTPUT_TOKENS must be between 128 and 65536")
    if not 1 <= gemini_max_page_regions <= 1000:
        raise ValueError("HTR_GEMINI_MAX_PAGE_REGIONS must be between 1 and 1000")
    data_root = Path(values.get("HTR_DATA_ROOT", str(project_root / "data"))).resolve()
    environment = values.get("HTR_API_ENV", "development")
    return Settings(
        environment,
        values.get("HTR_API_HOST", "127.0.0.1"),
        port,
        heartbeat,
        Path(values.get("HTR_DATABASE_PATH", str(data_root / "studio.sqlite3"))).resolve(),
        Path(values.get("HTR_STORAGE_ROOT", str(data_root / "assets"))).resolve(),
        int(values.get("HTR_SESSION_TTL_SECONDS", "28800")),
        values.get("HTR_SESSION_COOKIE_NAME", "htr_session"),
        values.get("HTR_COOKIE_SECURE", "true" if environment == "production" else "false").lower() == "true",
        int(values.get("HTR_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024))),
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
        craft_enabled,
        craft_max_edge,
        kraken_endpoint,
        kraken_timeout_seconds,
        line_crop_padding,
        trocr_num_beams,
        trocr_max_new_tokens,
        trocr_batch_size,
        trocr_adapter_mode,
        ocr_provider,
        gemini_mode,
        gemini_model,
        values.get("OPENROUTER_API_KEY") or None,
        gemini_timeout_seconds,
        gemini_thinking_level,
        gemini_max_output_tokens,
        gemini_max_page_regions,
        int(values.get("HTR_ACCOUNT_ATTEMPT_LIMIT", "5")),
        int(values.get("HTR_ACCOUNT_ATTEMPT_WINDOW_SECONDS", "900")),
    )


settings = read_settings()
