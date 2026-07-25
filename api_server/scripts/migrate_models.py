from __future__ import annotations

"""Copy the approved S01 model artifacts into the new API project safely.

The source manifest is intentionally read-only evidence.  This script refuses
symlinks, overwrites, missing entries, or a checksum mismatch before it writes
the destination manifest.  It never changes the legacy source directories.
"""

import argparse
import hashlib
import json
import shutil
import tempfile
from pathlib import Path
from typing import Any


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _read_manifest(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    artifacts = payload.get("artifacts")
    if payload.get("schema_version") != 1 or not isinstance(artifacts, list):
        raise ValueError("source manifest has an unsupported schema")
    required = {"path", "size_bytes", "sha256"}
    if not all(isinstance(item, dict) and required <= item.keys() for item in artifacts):
        raise ValueError("source manifest contains an invalid artifact")
    return artifacts


def _safe_relative(value: str) -> Path:
    path = Path(value)
    if path.is_absolute() or ".." in path.parts or len(path.parts) != 2:
        raise ValueError("source manifest contains an unsafe artifact path")
    if path.parts[0] not in {"model", "best_adapter"}:
        raise ValueError("source manifest points outside the approved model roots")
    return path


def _verify_source(source_root: Path, artifact: dict[str, Any]) -> Path:
    relative = _safe_relative(str(artifact["path"]))
    source = (source_root / relative).resolve()
    if not source.is_relative_to(source_root.resolve()) or source.is_symlink() or not source.is_file():
        raise ValueError(f"source artifact is missing or unsafe: {relative.as_posix()}")
    if source.stat().st_size != int(artifact["size_bytes"]) or _sha256(source) != artifact["sha256"]:
        raise ValueError(f"source artifact checksum mismatch: {relative.as_posix()}")
    return source


def migrate(*, source_root: Path, source_manifest: Path, models_root: Path) -> Path:
    artifacts = _read_manifest(source_manifest)
    verified = [(artifact, _verify_source(source_root, artifact)) for artifact in artifacts]
    destination_root = models_root.resolve()
    targets = {"model": destination_root / "trocr", "best_adapter": destination_root / "tajik_rslora"}
    if any(path.exists() for path in targets.values()):
        raise FileExistsError("target model directories already exist; refusing to overwrite")

    destination_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="model-migration-", dir=destination_root) as temporary:
        temporary_root = Path(temporary)
        copied: list[dict[str, Any]] = []
        for artifact, source in verified:
            relative = _safe_relative(str(artifact["path"]))
            target_group = "trocr" if relative.parts[0] == "model" else "tajik_rslora"
            destination = temporary_root / target_group / relative.name
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
            if destination.stat().st_size != int(artifact["size_bytes"]) or _sha256(destination) != artifact["sha256"]:
                raise ValueError(f"destination checksum mismatch: {relative.as_posix()}")
            copied.append(
                {
                    "path": f"{target_group}/{relative.name}",
                    "size_bytes": int(artifact["size_bytes"]),
                    "sha256": str(artifact["sha256"]),
                }
            )
        for group, target in targets.items():
            source = temporary_root / ("trocr" if group == "model" else "tajik_rslora")
            source.replace(target)

    source_manifest_sha256 = _sha256(source_manifest)
    manifest = {
        "schema_version": 1,
        "source_manifest_sha256": source_manifest_sha256,
        "models": {
            "trocr": {"version": "trocr-base-tajik-v1", "artifacts": [item for item in copied if item["path"].startswith("trocr/")]},
            "tajik_rslora": {"version": "tajik-rslora-v1", "artifacts": [item for item in copied if item["path"].startswith("tajik_rslora/")]},
        },
    }
    destination_manifest = destination_root / "manifest.json"
    destination_manifest.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return destination_manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--models-root", type=Path, required=True)
    arguments = parser.parse_args()
    manifest = migrate(
        source_root=arguments.source_root,
        source_manifest=arguments.source_manifest,
        models_root=arguments.models_root,
    )
    print(f"Model migration verified; manifest={manifest.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
