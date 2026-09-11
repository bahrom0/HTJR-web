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
    database_url: str | None
    database_path: Path
    storage_root: Path
    supabase_url: str | None
    supabase_key: str | None
    supabase_bucket: str
    openrouter_api_key: str | None
    ocr_provider: str
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

    @property
    def gemini_mode(self) -> str:
        return "page"


def read_settings(source: dict[str, str] | None = None, *, config_path: Path | None = None) -> Settings:
    values = environ if source is None else source
    project_root = Path(__file__).resolve().parents[2]

    # Defaults
    ocr_provider = "gemini"
    ocr_model = "google/gemini-2.5-flash"
    ocr_timeout_seconds = 60.0
    ocr_thinking_level = "low"
    ocr_max_output_tokens = 4096
    ocr_max_page_regions = 200

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
        database_url=database_url,
        database_path=db_path,
        storage_root=storage_root,
        supabase_url=supabase_url,
        supabase_key=supabase_key,
        supabase_bucket=supabase_bucket,
        openrouter_api_key=openrouter_api_key,
        ocr_provider=ocr_provider,
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
    )


settings = read_settings()
