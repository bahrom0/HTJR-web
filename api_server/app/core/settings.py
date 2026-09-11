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
    worker_heartbeat_seconds: float
    database_url: str | None
    database_path: Path
    storage_root: Path
    session_ttl_seconds: int
    cookie_name: str
    cookie_secure: bool
    supabase_url: str | None
    supabase_key: str | None
    supabase_bucket: str
    openrouter_api_key: str | None
    ocr_provider: str
    gemini_mode: str
    ocr_model: str
    ocr_timeout_seconds: float
    ocr_thinking_level: str
    ocr_max_output_tokens: int
    ocr_max_page_regions: int
    upload_max_bytes: int
    image_max_pixels: int
    image_max_dimension: int
    prepared_max_edge: int
    preview_max_edge: int
    job_queue_capacity: int
    job_max_attempts: int
    worker_lease_seconds: float
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
    account_attempt_limit: int
    account_attempt_window_seconds: int

    # Backward-compatibility aliases
    @property
    def gemini_model(self) -> str:
        return self.ocr_model

    @property
    def gemini_timeout_seconds(self) -> float:
        return self.ocr_timeout_seconds

    @property
    def gemini_thinking_level(self) -> str:
        return self.ocr_thinking_level

    @property
    def gemini_max_output_tokens(self) -> int:
        return self.ocr_max_output_tokens

    @property
    def gemini_max_page_regions(self) -> int:
        return self.ocr_max_page_regions

def read_settings(source: dict[str, str] | None = None, *, config_path: Path | None = None) -> Settings:
    values = environ if source is None else source
    project_root = Path(__file__).resolve().parents[2]

    # Defaults
    ocr_provider = "trocr"
    gemini_mode = "page"
    ocr_model = "google/gemini-3.8-flash:floor"
    ocr_timeout_seconds = 60.0
    ocr_thinking_level = "low"
    ocr_max_output_tokens = 4096
    ocr_max_page_regions = 200
    ml_device = "cpu"
    craft_enabled = False
    craft_max_edge = 2048
    kraken_endpoint = "http://127.0.0.1:8011"
    kraken_timeout_seconds = 180.0
    line_crop_padding = 0.08
    trocr_num_beams = 1
    trocr_max_new_tokens = 128
    trocr_batch_size = 1
    trocr_adapter_mode = "none"

    config_file = config_path or project_root / "config.toml"
    if config_file.is_file():
        try:
            with config_file.open("rb") as f:
                raw = tomllib.load(f)
                ml = raw.get("ml", {})
                if isinstance(ml, dict):
                    ocr_provider = ml.get("ocr_provider", ocr_provider)
                    ocr_model = ml.get("gemini_model", ml.get("ocr_model", ocr_model))
                    ocr_timeout_seconds = float(ml.get("gemini_timeout_seconds", ocr_timeout_seconds))
                    ocr_thinking_level = ml.get("gemini_thinking_level", ocr_thinking_level)
                    ocr_max_output_tokens = int(ml.get("gemini_max_output_tokens", ocr_max_output_tokens))
                    ocr_max_page_regions = int(ml.get("gemini_max_page_regions", ocr_max_page_regions))
                    gemini_mode = str(ml.get("gemini_mode", gemini_mode))
                    ml_device = "auto" if bool(ml.get("CUDA", False)) else "cpu"
                    craft_enabled = bool(ml.get("CRAFT", craft_enabled))
                    craft_max_edge = int(ml.get("craft_max_edge", craft_max_edge))
                    kraken_endpoint = str(ml.get("kraken_endpoint", kraken_endpoint))
                    kraken_timeout_seconds = float(ml.get("kraken_timeout_seconds", kraken_timeout_seconds))
                    line_crop_padding = float(ml.get("line_crop_padding", line_crop_padding))
                    trocr_num_beams = int(ml.get("trocr_num_beams", trocr_num_beams))
                    trocr_max_new_tokens = int(ml.get("trocr_max_new_tokens", trocr_max_new_tokens))
                    trocr_batch_size = int(ml.get("trocr_batch_size", trocr_batch_size))
                    trocr_adapter_mode = str(ml.get("trocr_adapter_mode", trocr_adapter_mode))
        except Exception:
            pass

    # Environment variable overrides
    ocr_model = values.get("HTR_OCR_MODEL", values.get("HTR_GEMINI_MODEL", ocr_model))
    openrouter_api_key = values.get("OPENROUTER_API_KEY")

    supabase_url = values.get("SUPABASE_URL")
    supabase_key = values.get("SUPABASE_SERVICE_ROLE_KEY", values.get("SUPABASE_KEY"))
    supabase_bucket = values.get("SUPABASE_BUCKET", "htr-uploads")

    database_url = values.get("DATABASE_URL")
    default_data_root = Path("/tmp/htr-data") if values.get("VERCEL") else project_root / "data"
    data_root = Path(values.get("HTR_DATA_ROOT", str(default_data_root))).resolve()
    db_path = Path(values.get("HTR_DATABASE_PATH", str(data_root / "studio.sqlite3"))).resolve()
    storage_root = Path(values.get("HTR_STORAGE_ROOT", str(data_root / "assets"))).resolve()

    port = int(values.get("PORT", values.get("HTR_API_PORT", "8000")))
    environment = values.get("HTR_API_ENV", "production")

    return Settings(
        environment=environment,
        host=values.get("HTR_API_HOST", "0.0.0.0"),
        port=port,
        worker_heartbeat_seconds=float(values.get("HTR_WORKER_HEARTBEAT_SECONDS", "30")),
        database_url=database_url,
        database_path=db_path,
        storage_root=storage_root,
        session_ttl_seconds=int(values.get("HTR_SESSION_TTL_SECONDS", "28800")),
        cookie_name=values.get("HTR_COOKIE_NAME", "htr_session"),
        cookie_secure=values.get("HTR_COOKIE_SECURE", "false").lower() in {"1", "true", "yes", "on"},
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        supabase_bucket=supabase_bucket,
        openrouter_api_key=openrouter_api_key,
        ocr_provider=values.get("HTR_OCR_PROVIDER", ocr_provider),
        gemini_mode=values.get("HTR_GEMINI_MODE", gemini_mode),
        ocr_model=ocr_model,
        ocr_timeout_seconds=float(values.get("HTR_OCR_TIMEOUT_SECONDS", str(ocr_timeout_seconds))),
        ocr_thinking_level=values.get("HTR_OCR_THINKING_LEVEL", ocr_thinking_level),
        ocr_max_output_tokens=int(values.get("HTR_OCR_MAX_OUTPUT_TOKENS", str(ocr_max_output_tokens))),
        ocr_max_page_regions=int(values.get("HTR_OCR_MAX_PAGE_REGIONS", str(ocr_max_page_regions))),
        upload_max_bytes=int(values.get("HTR_UPLOAD_MAX_BYTES", str(10 * 1024 * 1024))),
        image_max_pixels=int(values.get("HTR_IMAGE_MAX_PIXELS", "40000000")),
        image_max_dimension=int(values.get("HTR_IMAGE_MAX_DIMENSION", "12000")),
        prepared_max_edge=int(values.get("HTR_PREPARED_MAX_EDGE", "4096")),
        preview_max_edge=int(values.get("HTR_PREVIEW_MAX_EDGE", "1600")),
        job_queue_capacity=int(values.get("HTR_JOB_QUEUE_CAPACITY", "32")),
        job_max_attempts=int(values.get("HTR_JOB_MAX_ATTEMPTS", "3")),
        worker_lease_seconds=float(values.get("HTR_WORKER_LEASE_SECONDS", "90")),
        worker_poll_seconds=float(values.get("HTR_WORKER_POLL_SECONDS", "1")),
        sse_heartbeat_seconds=float(values.get("HTR_SSE_HEARTBEAT_SECONDS", "15")),
        sse_poll_seconds=float(values.get("HTR_SSE_POLL_SECONDS", "0.5")),
        ml_device=values.get("HTR_ML_DEVICE", ml_device),
        craft_enabled=values.get("HTR_CRAFT_ENABLED", str(craft_enabled)).lower() in {"1", "true", "yes", "on"},
        craft_max_edge=int(values.get("HTR_CRAFT_MAX_EDGE", str(craft_max_edge))),
        kraken_endpoint=values.get("HTR_KRAKEN_ENDPOINT", kraken_endpoint),
        kraken_timeout_seconds=float(values.get("HTR_KRAKEN_TIMEOUT_SECONDS", str(kraken_timeout_seconds))),
        line_crop_padding=float(values.get("HTR_LINE_CROP_PADDING", str(line_crop_padding))),
        trocr_num_beams=int(values.get("HTR_TROCR_NUM_BEAMS", str(trocr_num_beams))),
        trocr_max_new_tokens=int(values.get("HTR_TROCR_MAX_NEW_TOKENS", str(trocr_max_new_tokens))),
        trocr_batch_size=int(values.get("HTR_TROCR_BATCH_SIZE", str(trocr_batch_size))),
        trocr_adapter_mode=values.get("HTR_TROCR_ADAPTER_MODE", trocr_adapter_mode),
        account_attempt_limit=int(values.get("HTR_ACCOUNT_ATTEMPT_LIMIT", "5")),
        account_attempt_window_seconds=int(values.get("HTR_ACCOUNT_ATTEMPT_WINDOW_SECONDS", "900")),
    )


settings = read_settings()
