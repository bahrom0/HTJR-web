from __future__ import annotations

import argparse
import json
from pathlib import Path

from PIL import Image

from app.core.settings import settings
from app.ml.kraken_runtime import KrakenRuntime


def main() -> int:
    parser = argparse.ArgumentParser(description="Run real Kraken line segmentation on one local image")
    parser.add_argument("image", type=Path)
    parser.add_argument("--endpoint", default=settings.kraken_endpoint)
    arguments = parser.parse_args()

    runtime = KrakenRuntime(arguments.endpoint, timeout_seconds=settings.kraken_timeout_seconds)
    with Image.open(arguments.image) as source:
        detection = runtime.detect(source)
    evidence = runtime.evidence
    if evidence is None:
        raise RuntimeError("kraken_readiness_evidence_missing")
    if any(len(line.boundary) < 3 for line in detection.lines):
        raise RuntimeError("kraken_boundary_invalid")

    print(
        json.dumps(
            {
                "image": str(arguments.image.resolve()),
                "image_size": [detection.width, detection.height],
                "line_count": len(detection.lines),
                "detector_version": detection.detector_version,
                "duration_ms": detection.duration_ms,
                "warmup_ms": detection.warmup_ms,
                "device": evidence.device,
                "precision": evidence.dtype,
                "boundary_point_counts": [len(line.boundary) for line in detection.lines],
                "baseline_point_counts": [len(line.baseline) for line in detection.lines],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
