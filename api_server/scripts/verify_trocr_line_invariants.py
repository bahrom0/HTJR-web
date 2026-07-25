from __future__ import annotations

"""Exercise real rsLoRA generation on representative, empty, and long crops.

Recognition text is intentionally reduced to hashes.  The script proves that
each input goes through ``TrocrRuntime.recognize`` rather than treating a
transport response as model evidence.
"""

import argparse
import hashlib
import json
from pathlib import Path

from PIL import Image

from app.ml.trocr_runtime import TrocrRuntime, TrocrRuntimeError


def _observation(name: str, generation) -> dict[str, object]:
    if generation.generated_token_count < 1 or generation.decoding_steps < 0 or generation.duration_ms < 0:
        raise AssertionError(f"{name}_generation_metadata_invalid")
    return {
        "duration_ms": generation.duration_ms,
        "generated_token_count": generation.generated_token_count,
        "decoding_steps": generation.decoding_steps,
        "mean_token_log_probability": generation.mean_token_log_probability,
        "text_sha256": hashlib.sha256(generation.text.encode("utf-8")).hexdigest(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--num-beams", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=16)
    arguments = parser.parse_args()
    if not arguments.image.is_file():
        parser.error("--image must be a readable local image")
    if not 1 <= arguments.num_beams <= 4 or not 1 <= arguments.max_new_tokens <= 256:
        parser.error("generation values are outside safe bounds")

    with Image.open(arguments.image) as source:
        representative = source.convert("RGB")
    long_line = representative.resize((max(1024, representative.width * 4), max(64, representative.height)), Image.Resampling.LANCZOS)
    empty = Image.new("RGB", (max(384, representative.width), max(64, representative.height)), "white")
    runtime = TrocrRuntime(Path(__file__).resolve().parents[1] / "models", device=arguments.device)
    try:
        evidence = runtime.warmup()
        observations = {
            "representative": _observation(
                "representative",
                runtime.recognize(representative, num_beams=arguments.num_beams, max_new_tokens=arguments.max_new_tokens),
            ),
            "empty": _observation(
                "empty",
                runtime.recognize(empty, num_beams=arguments.num_beams, max_new_tokens=arguments.max_new_tokens),
            ),
            "long": _observation(
                "long",
                runtime.recognize(long_line, num_beams=arguments.num_beams, max_new_tokens=arguments.max_new_tokens),
            ),
        }
    except (AssertionError, OSError, TrocrRuntimeError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
        return 1
    finally:
        representative.close()
        long_line.close()
        empty.close()
        runtime.close()

    print(
        json.dumps(
            {
                "status": "ready",
                "device": evidence.device,
                "dtype": evidence.dtype,
                "lora_tensor_count": evidence.lora_tensor_count,
                "nonzero_lora_parameter_count": evidence.nonzero_lora_parameter_count,
                "observations": observations,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
