from __future__ import annotations

"""Run the local CRAFT -> base TrOCR path without exposing image or text data."""

import argparse
import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from PIL import Image

from app.ml.craft_runtime import CraftRuntime, CraftRuntimeError
from app.ml.trocr_runtime import TrocrRuntime, TrocrRuntimeError


def _crop_from_first_detection(image: Image.Image, boxes: tuple[tuple[float, float, float, float], ...]) -> Image.Image:
    if not boxes:
        raise ValueError("craft_no_regions_detected")
    left, top, right, bottom = boxes[0]
    margin = max(2, round(max(right - left, bottom - top) * 0.08))
    return image.convert("RGB").crop(
        (
            max(0, int(left) - margin),
            max(0, int(top) - margin),
            min(image.width, int(right) + margin),
            min(image.height, int(bottom) + margin),
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True, help="Local representative page or line image")
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--craft-max-edge", type=int, default=2048)
    parser.add_argument("--num-beams", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=128)
    arguments = parser.parse_args()
    if not 256 <= arguments.craft_max_edge <= 4096:
        parser.error("--craft-max-edge must be between 256 and 4096")
    if not 1 <= arguments.num_beams <= 4 or not 1 <= arguments.max_new_tokens <= 256:
        parser.error("generation values are outside safe bounds")
    if not arguments.image.is_file():
        parser.error("--image must be a readable local image")

    models_root = Path(__file__).resolve().parents[1] / "models"
    craft = CraftRuntime(models_root, max_edge=arguments.craft_max_edge, device=arguments.device)
    trocr = TrocrRuntime(models_root, device=arguments.device)
    try:
        craft_warmup = craft.warmup()
        with Image.open(arguments.image) as source:
            detection = craft.detect(source)
            crop = _crop_from_first_detection(source, detection.boxes)
        trocr_evidence = trocr.warmup()
        generation = trocr.recognize(crop, num_beams=arguments.num_beams, max_new_tokens=arguments.max_new_tokens)
    except (CraftRuntimeError, TrocrRuntimeError, OSError, ValueError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
        return 1
    finally:
        craft.close()
        trocr.close()

    # Text is intentionally represented only by a digest: this is evidence of
    # a real generate() call without leaking recognition content to logs.
    payload = {
        "status": "ready",
        "craft": {
            "warmup_duration_ms": craft_warmup,
            "detector_version": detection.detector_version,
            "thresholds_version": detection.thresholds_version,
            "region_count": len(detection.boxes),
            "duration_ms": detection.duration_ms,
        },
        "trocr": {
            **asdict(trocr_evidence),
            "generation_duration_ms": generation.duration_ms,
            "generated_token_count": generation.generated_token_count,
            "decoding_steps": generation.decoding_steps,
            "mean_token_log_probability": generation.mean_token_log_probability,
            "text_sha256": hashlib.sha256(generation.text.encode("utf-8")).hexdigest(),
        },
    }
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
