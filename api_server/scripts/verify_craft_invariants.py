from __future__ import annotations

"""Exercise real local CRAFT on representative and boundary image variants."""

import argparse
import json
from pathlib import Path

import numpy as np
from PIL import Image

from app.ml.craft_runtime import CraftRuntime, CraftRuntimeError
from app.services.images import source_to_rgb


def _assert_real_geometry(name: str, result) -> dict[str, object]:
    for box, polygon, score in zip(result.boxes, result.polygons, result.scores, strict=True):
        left, top, right, bottom = box
        if not (0 <= left < right <= result.width and 0 <= top < bottom <= result.height):
            raise AssertionError(f"{name}: detector box escapes the source image")
        if not polygon or any(not (0 <= x <= result.width and 0 <= y <= result.height) for x, y in polygon):
            raise AssertionError(f"{name}: detector polygon escapes the source image")
        if not 0 <= score <= 1:
            raise AssertionError(f"{name}: detector score is outside [0,1]")
    return {
        "input_size": [result.width, result.height],
        "region_count": len(result.boxes),
        "max_region_area_fraction": max(
            ((right - left) * (bottom - top)) / float(result.width * result.height)
            for left, top, right, bottom in result.boxes
        )
        if result.boxes
        else 0.0,
        "duration_ms": result.duration_ms,
        "score_map_shape": list(result.text_score_map.shape),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--craft-max-edge", type=int, default=2048)
    arguments = parser.parse_args()
    if not arguments.image.is_file():
        parser.error("--image must be a readable local image")
    if not 256 <= arguments.craft_max_edge <= 4096:
        parser.error("--craft-max-edge must be between 256 and 4096")

    with Image.open(arguments.image) as source:
        one_line = source_to_rgb(source)
    random = np.random.default_rng(20260719)
    noise = Image.fromarray(random.integers(0, 256, (one_line.height, one_line.width, 3), dtype=np.uint8), "RGB")
    cases = {
        "one_line": one_line,
        "empty": Image.new("RGB", one_line.size, "white"),
        "noisy": noise,
        "rotated": one_line.rotate(3, expand=True, resample=Image.Resampling.BICUBIC, fillcolor="white"),
        "large": one_line.resize((max(4097, one_line.width * 16), max(257, one_line.height * 16)), Image.Resampling.BILINEAR),
    }
    runtime = CraftRuntime(Path(__file__).resolve().parents[1] / "models", max_edge=arguments.craft_max_edge, device=arguments.device)
    try:
        warmup = runtime.warmup()
        observations = {name: _assert_real_geometry(name, runtime.detect(image)) for name, image in cases.items()}
    except (CraftRuntimeError, OSError, AssertionError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
        return 1
    finally:
        runtime.close()
        for image in cases.values():
            image.close()
    if observations["one_line"]["region_count"] < 1:
        print(json.dumps({"status": "failed", "code": "craft_representative_line_not_detected", "cases": observations}, sort_keys=True))
        return 1
    if observations["one_line"]["max_region_area_fraction"] >= 0.95:
        print(json.dumps({"status": "failed", "code": "craft_one_line_box_is_full_page", "cases": observations}, sort_keys=True))
        return 1
    if observations["empty"]["region_count"] != 0:
        print(json.dumps({"status": "failed", "code": "craft_empty_page_false_positive", "cases": observations}, sort_keys=True))
        return 1
    print(json.dumps({"status": "ready", "warmup_duration_ms": warmup, "cases": observations}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
