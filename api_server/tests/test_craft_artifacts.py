from __future__ import annotations

import hashlib
import json

from app.ml.craft import inspect_craft_artifacts


def test_missing_craft_artifacts_are_an_explicit_readiness_failure(tmp_path) -> None:
    status = inspect_craft_artifacts(tmp_path)
    assert status.ready is False and status.code == "craft_artifacts_missing"


def test_manifest_validates_local_weight_checksum_and_rejects_escape(tmp_path) -> None:
    craft = tmp_path / "craft"
    craft.mkdir()
    weights = craft / "craft_weights.pth"
    weights.write_bytes(b"verified-local-weight-fixture")
    manifest = {
        "schema_version": 1,
        "model_version": "craft-test-v1",
        "weights": {
            "path": weights.name,
            "sha256": hashlib.sha256(weights.read_bytes()).hexdigest(),
            "byte_size": weights.stat().st_size,
            "provenance": "test fixture",
            "license": "test-only",
        },
    }
    (craft / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert inspect_craft_artifacts(tmp_path).code == "ready"
    manifest["weights"]["path"] = "../craft_weights.pth"
    (craft / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert inspect_craft_artifacts(tmp_path).code == "craft_manifest_invalid"
