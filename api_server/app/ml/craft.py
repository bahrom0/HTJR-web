from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class CraftArtifactStatus:
    ready: bool
    code: str
    model_version: str | None = None
    weight_path: Path | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def inspect_craft_artifacts(models_root: Path) -> CraftArtifactStatus:
    """Validate only local, manifest-backed CRAFT artifacts without importing ML libraries."""
    craft_root = (models_root / "craft").resolve()
    manifest_path = craft_root / "manifest.json"
    if not manifest_path.is_file():
        return CraftArtifactStatus(False, "craft_artifacts_missing")
    try:
        # Accept the BOM emitted by Windows PowerShell while retaining strict JSON.
        manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return CraftArtifactStatus(False, "craft_manifest_invalid")
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        return CraftArtifactStatus(False, "craft_manifest_invalid")
    model_version = manifest.get("model_version")
    if not isinstance(model_version, str) or not model_version:
        return CraftArtifactStatus(False, "craft_manifest_invalid")
    artifact = manifest.get("weights")
    if not isinstance(artifact, dict):
        return CraftArtifactStatus(False, "craft_manifest_invalid")
    relative_path = artifact.get("path")
    expected_sha = artifact.get("sha256")
    expected_size = artifact.get("byte_size")
    provenance = artifact.get("provenance")
    license_name = artifact.get("license")
    if (
        not isinstance(relative_path, str)
        or not isinstance(expected_sha, str)
        or len(expected_sha) != 64
        or not isinstance(expected_size, int)
        or expected_size <= 0
        or not isinstance(provenance, str)
        or not provenance
        or not isinstance(license_name, str)
        or not license_name
    ):
        return CraftArtifactStatus(False, "craft_manifest_invalid")
    candidate = (craft_root / relative_path).resolve()
    try:
        if candidate == craft_root or craft_root not in candidate.parents or candidate.is_symlink():
            return CraftArtifactStatus(False, "craft_manifest_invalid")
        if not candidate.is_file():
            return CraftArtifactStatus(False, "craft_weights_missing", model_version)
        if candidate.stat().st_size != expected_size:
            return CraftArtifactStatus(False, "craft_weights_corrupt", model_version)
        if _sha256(candidate).lower() != expected_sha.lower():
            return CraftArtifactStatus(False, "craft_weights_corrupt", model_version)
    except OSError:
        return CraftArtifactStatus(False, "craft_weights_unreadable", model_version)
    return CraftArtifactStatus(True, "ready", model_version, candidate)


def craft_models_root() -> Path:
    return Path(__file__).resolve().parents[2] / "models"


def craft_status() -> CraftArtifactStatus:
    return inspect_craft_artifacts(craft_models_root())
