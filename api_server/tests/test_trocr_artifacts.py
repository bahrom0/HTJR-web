from __future__ import annotations

import hashlib
import json
import struct
import sys
from pathlib import Path

import pytest
import torch

from app.ml.trocr_runtime import (
    TrocrRuntimeError,
    _score_generated_tokens,
    _is_windows_pagefile_error,
    _runtime_modules,
    _stream_safetensors_state,
    inspect_trocr_artifacts,
)
from scripts.migrate_models import migrate


def _artifact(path: str, payload: bytes) -> dict[str, object]:
    return {"path": path, "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest()}


def test_trocr_manifest_rejects_missing_base_adapter_and_corrupt_artifacts(tmp_path: Path) -> None:
    assert inspect_trocr_artifacts(tmp_path).code == "trocr_artifacts_missing"
    manifest = {"schema_version": 1, "models": {"trocr": {"version": "base-v1", "artifacts": []}}}
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert inspect_trocr_artifacts(tmp_path).code == "trocr_manifest_invalid"

    manifest["models"]["trocr"]["artifacts"] = [_artifact("trocr/config.json", b"base")]
    manifest["models"]["tajik_rslora"] = {
        "version": "adapter-v1",
        "artifacts": [_artifact("tajik_rslora/adapter_config.json", b'{"use_rslora":true}')],
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert inspect_trocr_artifacts(tmp_path).code == "trocr_artifacts_corrupt"


def test_trocr_manifest_accepts_base_only_without_adapter_metadata(tmp_path: Path) -> None:
    payload = b"base-model-fixture"
    (tmp_path / "trocr").mkdir()
    (tmp_path / "trocr" / "config.json").write_bytes(payload)
    manifest = {
        "schema_version": 1,
        "models": {
            "trocr": {"version": "base-v1", "artifacts": [_artifact("trocr/config.json", payload)]},
            # A broken optional adapter must not make base-only readiness fail.
            "tajik_rslora": {
                "version": "adapter-v1",
                "artifacts": [_artifact("tajik_rslora/config.json", b"missing")],
            },
        },
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    status = inspect_trocr_artifacts(tmp_path)

    assert status.ready is True
    assert status.model_version == "base-v1"
    assert status.adapter_version is None
    assert status.adapter_root is None
    assert inspect_trocr_artifacts(tmp_path, adapter_mode="rslora").code == "trocr_artifacts_corrupt"


def test_sequence_confidence_excludes_padding_and_tokens_after_eos() -> None:
    score, token_count = _score_generated_tokens(
        [101, 102, 2, 1, 1],
        [-0.2, -0.4, -0.6, -99.0, -99.0],
        eos_token_id=2,
        pad_token_id=1,
    )

    assert score == pytest.approx(-0.3)
    assert token_count == 2


def test_sequence_confidence_is_individual_for_rows_with_different_lengths() -> None:
    first = _score_generated_tokens([10, 2, 1, 1], [-0.1, -0.2, -50.0, -50.0], eos_token_id=2, pad_token_id=1)
    second = _score_generated_tokens([20, 21, 22, 2], [-0.9, -0.9, -0.9, -0.1], eos_token_id=2, pad_token_id=1)

    assert first == (pytest.approx(-0.1), 1)
    assert second == (pytest.approx(-0.9), 3)


def test_base_runtime_module_loader_does_not_import_peft() -> None:
    sys.modules.pop("peft", None)

    _runtime_modules()

    assert "peft" not in sys.modules


def test_model_migration_copies_verified_artifacts_and_never_changes_source(tmp_path: Path) -> None:
    source = tmp_path / "legacy"
    (source / "model").mkdir(parents=True)
    (source / "best_adapter").mkdir()
    base_payload, adapter_payload = b"base-model-fixture", b"adapter-fixture"
    (source / "model" / "config.json").write_bytes(base_payload)
    (source / "best_adapter" / "adapter_config.json").write_bytes(adapter_payload)
    source_manifest = tmp_path / "source-manifest.json"
    source_manifest.write_text(
        json.dumps({"schema_version": 1, "artifacts": [_artifact("model/config.json", base_payload), _artifact("best_adapter/adapter_config.json", adapter_payload)]}),
        encoding="utf-8",
    )
    destination = tmp_path / "models"
    manifest = migrate(source_root=source, source_manifest=source_manifest, models_root=destination)
    assert (source / "model" / "config.json").read_bytes() == base_payload
    assert (source / "best_adapter" / "adapter_config.json").read_bytes() == adapter_payload
    assert (destination / "trocr" / "config.json").read_bytes() == base_payload
    assert (destination / "tajik_rslora" / "adapter_config.json").read_bytes() == adapter_payload
    copied = json.loads(manifest.read_text(encoding="utf-8"))
    assert copied["source_manifest_sha256"] == hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    with pytest.raises(FileExistsError):
        migrate(source_root=source, source_manifest=source_manifest, models_root=destination)


def test_streaming_safetensors_loads_tensor_without_safe_open_mmap(tmp_path: Path) -> None:
    path = tmp_path / "tiny.safetensors"
    values = struct.pack("<2f", 1.25, -2.5)
    header = json.dumps(
        {"tensor": {"dtype": "F32", "shape": [2], "data_offsets": [0, len(values)]}},
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header + values)

    state = _stream_safetensors_state(path, torch=torch, device=torch.device("cpu"))

    assert tuple(state) == ("tensor",)
    assert state["tensor"].tolist() == pytest.approx([1.25, -2.5])


def test_streaming_safetensors_rejects_overlapping_ranges_and_classifies_winerror_1455(tmp_path: Path) -> None:
    path = tmp_path / "invalid.safetensors"
    payload = struct.pack("<2f", 1.0, 2.0)
    header = json.dumps(
        {
            "first": {"dtype": "F32", "shape": [1], "data_offsets": [0, 4]},
            "second": {"dtype": "F32", "shape": [1], "data_offsets": [2, 6]},
        },
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(struct.pack("<Q", len(header)) + header + payload)

    with pytest.raises(TrocrRuntimeError, match="trocr_streaming_weights_invalid"):
        _stream_safetensors_state(path, torch=torch, device=torch.device("cpu"))

    error = OSError("pagefile exhausted")
    error.winerror = 1455  # type: ignore[attr-defined]
    assert _is_windows_pagefile_error(error) is True
