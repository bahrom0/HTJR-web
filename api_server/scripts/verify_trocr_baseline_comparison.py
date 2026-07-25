from __future__ import annotations

"""Compare local base TrOCR and the verified rsLoRA runtime without text logs.

Each model runs in a separate child process, so the comparison never keeps two
large graphs or two allocator pools in memory.  It is a verification utility,
not a product inference endpoint.
"""

import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path

from PIL import Image

from app.ml.trocr_runtime import TrocrRuntime, TrocrRuntimeError, _load_windows_streamed_model, _runtime_modules


def _payload(output: str) -> dict[str, object] | None:
    for line in reversed(output.splitlines()):
        try:
            value = json.loads(line)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return None


def _image(path: Path) -> Image.Image:
    with Image.open(path) as source:
        return source.convert("RGB")


def _base_child(arguments: argparse.Namespace) -> int:
    models_root = Path(__file__).resolve().parents[1] / "models"
    torch, _, _, _, transformer_types = _runtime_modules()
    TrOCRProcessor, VisionEncoderDecoderModel = transformer_types
    wants_cuda = arguments.device == "cuda" or (arguments.device == "auto" and torch.cuda.is_available())
    if arguments.device == "cuda" and not torch.cuda.is_available():
        print(json.dumps({"status": "failed", "code": "trocr_cuda_unavailable"}, sort_keys=True))
        return 1
    device = torch.device("cuda" if wants_cuda else "cpu")
    dtype = torch.float16 if wants_cuda or os.name == "nt" else torch.float32
    model = processor = image = inputs = pixel_values = output = None
    try:
        processor = TrOCRProcessor.from_pretrained(models_root / "trocr", local_files_only=True, use_fast=False)
        if os.name == "nt":
            model = _load_windows_streamed_model(
                models_root / "trocr",
                torch=torch,
                VisionEncoderDecoderModel=VisionEncoderDecoderModel,
                device=device,
                dtype=dtype,
            )
        else:
            model = VisionEncoderDecoderModel.from_pretrained(
                models_root / "trocr",
                local_files_only=True,
                low_cpu_mem_usage=True,
                use_safetensors=True,
            ).to(device=device, dtype=dtype).eval()
        tokenizer = processor.tokenizer
        for config in (model.config, model.generation_config):
            config.decoder_start_token_id = tokenizer.eos_token_id
            config.pad_token_id = tokenizer.pad_token_id
            config.eos_token_id = tokenizer.eos_token_id
        image = _image(arguments.image)
        inputs = processor(images=image, return_tensors="pt")
        pixel_values = inputs.pixel_values.to(device=device, dtype=dtype)
        started = time.perf_counter()
        with torch.inference_mode():
            output = model.generate(
                pixel_values,
                num_beams=arguments.num_beams,
                max_new_tokens=arguments.max_new_tokens,
                return_dict_in_generate=True,
                output_scores=True,
            )
            if device.type == "cuda":
                torch.cuda.synchronize(device)
        text = processor.batch_decode(output.sequences, skip_special_tokens=True)[0].strip()
        print(
            json.dumps(
                {
                    "status": "ready",
                    "kind": "baseline",
                    "device": str(device),
                    "dtype": str(dtype).removeprefix("torch."),
                    "duration_ms": round((time.perf_counter() - started) * 1000),
                    "generated_token_count": int(output.sequences.shape[-1]),
                    "decoding_steps": len(output.scores or ()),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, TrocrRuntimeError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
        return 1
    finally:
        if image is not None:
            image.close()
        del model, processor, image, inputs, pixel_values, output
        gc.collect()


def _adapter_child(arguments: argparse.Namespace) -> int:
    models_root = Path(__file__).resolve().parents[1] / "models"
    runtime = TrocrRuntime(models_root, device=arguments.device)
    image = None
    try:
        evidence = runtime.warmup()
        image = _image(arguments.image)
        generation = runtime.recognize(
            image,
            num_beams=arguments.num_beams,
            max_new_tokens=arguments.max_new_tokens,
        )
        print(
            json.dumps(
                {
                    "status": "ready",
                    "kind": "rslora",
                    "device": evidence.device,
                    "dtype": evidence.dtype,
                    "duration_ms": generation.duration_ms,
                    "generated_token_count": generation.generated_token_count,
                    "decoding_steps": generation.decoding_steps,
                    "lora_tensor_count": evidence.lora_tensor_count,
                    "nonzero_lora_parameter_count": evidence.nonzero_lora_parameter_count,
                    "text_sha256": hashlib.sha256(generation.text.encode("utf-8")).hexdigest(),
                },
                sort_keys=True,
            )
        )
        return 0
    except (OSError, TrocrRuntimeError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}, sort_keys=True))
        return 1
    finally:
        if image is not None:
            image.close()
        runtime.close()


def _parent(arguments: argparse.Namespace) -> int:
    command_base = [
        sys.executable,
        "-m",
        "scripts.verify_trocr_baseline_comparison",
        "--image",
        str(arguments.image.resolve()),
        "--device",
        arguments.device,
        "--num-beams",
        str(arguments.num_beams),
        "--max-new-tokens",
        str(arguments.max_new_tokens),
    ]
    observations: dict[str, dict[str, object]] = {}
    for child in ("baseline", "rslora"):
        completed = subprocess.run(
            [*command_base, "--child", child],
            cwd=Path(__file__).resolve().parents[1],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=1800,
            check=False,
        )
        payload = _payload(completed.stdout)
        if completed.returncode != 0 or payload is None or payload.get("status") != "ready":
            code = payload.get("code") if payload is not None else None
            print(json.dumps({"status": "failed", "stage": child, "code": code or "comparison_child_failed"}, sort_keys=True))
            return 1
        observations[child] = {key: value for key, value in payload.items() if key != "status"}
    print(json.dumps({"status": "ready", "baseline": observations["baseline"], "rslora": observations["rslora"]}, sort_keys=True))
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", type=Path, required=True)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="auto")
    parser.add_argument("--num-beams", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=16)
    parser.add_argument("--child", choices=("baseline", "rslora"))
    arguments = parser.parse_args()
    if not arguments.image.is_file():
        parser.error("--image must be a readable local image")
    if not 1 <= arguments.num_beams <= 4 or not 1 <= arguments.max_new_tokens <= 256:
        parser.error("generation values are outside safe bounds")
    if arguments.child == "baseline":
        return _base_child(arguments)
    if arguments.child == "rslora":
        return _adapter_child(arguments)
    return _parent(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
