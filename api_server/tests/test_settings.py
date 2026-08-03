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
    assert settings.kraken_endpoint == "http://127.0.0.1:8011"
    assert settings.kraken_timeout_seconds == 90


def test_cpu_project_config_disables_cuda_and_environment_can_override_it(tmp_path: Path) -> None:
    config_path = tmp_path / "config.toml"
    config_path.write_text("[ml]\nCUDA = false\nCRAFT = true\ntrocr_batch_size = 3\n", encoding="utf-8")

    cpu_settings = read_settings({}, config_path=config_path)
    diagnostic_settings = read_settings({"HTR_ML_DEVICE": "cuda", "HTR_TROCR_BATCH_SIZE": "2"}, config_path=config_path)

    assert cpu_settings.ml_device == "cpu"
    assert cpu_settings.craft_enabled is True
    assert cpu_settings.trocr_batch_size == 3
    assert diagnostic_settings.ml_device == "cuda"
    assert diagnostic_settings.trocr_batch_size == 2
