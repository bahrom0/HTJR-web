from pathlib import Path

from app.core.settings import read_settings


def test_cuda_project_config_uses_auto_device_and_batch_size(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[ml]\nCUDA = true\nCRAFT = false\ntrocr_batch_size = 4\n'
        'kraken_endpoint = "http://127.0.0.1:8011"\nkraken_timeout_seconds = 90\n',
        encoding="utf-8",
    )

    settings = read_settings({}, config_path=config_path)

    assert settings.ml_device == "auto"
    assert settings.craft_enabled is False
    assert settings.trocr_batch_size == 4
    assert settings.trocr_adapter_mode == "none"
    assert settings.kraken_endpoint == "http://127.0.0.1:8011"
    assert settings.kraken_timeout_seconds == 90
    assert settings.ocr_provider == "trocr"
    assert settings.gemini_mode == "page"
    assert settings.gemini_model == "google/gemini-3.8-flash:floor"
    assert settings.openrouter_api_key is None
    assert settings.gemini_thinking_level == "low"
    assert settings.upload_max_bytes == 10 * 1024 * 1024


def test_cpu_project_config_disables_cuda_and_environment_can_override_it(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[ml]\nCUDA = false\nCRAFT = true\ntrocr_batch_size = 3\n", encoding="utf-8")

    cpu_settings = read_settings({}, config_path=config_path)
    diagnostic_settings = read_settings(
        {"HTR_ML_DEVICE": "cuda", "HTR_TROCR_BATCH_SIZE": "2", "HTR_TROCR_ADAPTER_MODE": "rslora"},
        config_path=config_path,
    )

    assert cpu_settings.ml_device == "cpu"
    assert cpu_settings.craft_enabled is True
    assert cpu_settings.trocr_batch_size == 3
    assert diagnostic_settings.ml_device == "cuda"
    assert diagnostic_settings.trocr_batch_size == 2
    assert diagnostic_settings.trocr_adapter_mode == "rslora"


def test_gemini_project_config_and_environment_overrides(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        '[ml]\nocr_provider = "gemini"\ngemini_mode = "page"\n'
        'gemini_model = "google/gemini-3.8-flash:floor"\ngemini_timeout_seconds = 120\n'
        'gemini_thinking_level = "low"\ngemini_max_output_tokens = 4096\n'
        "gemini_max_page_regions = 200\n",
        encoding="utf-8",
    )

    settings = read_settings(
        {"OPENROUTER_API_KEY": "test-only", "HTR_GEMINI_MODE": "kraken"},
        config_path=config_path,
    )

    assert settings.ocr_provider == "gemini"
    assert settings.gemini_mode == "kraken"
    assert settings.openrouter_api_key == "test-only"
    assert settings.gemini_timeout_seconds == 120
    assert settings.gemini_max_output_tokens == 4096
    assert settings.gemini_max_page_regions == 200
