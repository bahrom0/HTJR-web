from __future__ import annotations

"""Small local benchmark for the production base-only two-observation slice.

The benchmark reads already committed line crops from the local SQLite store,
keeps one TrOCR instance resident, and never writes application data.  Ground
truth is optional via a JSON object keyed by ``storage_key``.
"""

import argparse
import json
import time
from pathlib import Path
from typing import Any

from PIL import Image

from app.core.storage import FileStorage
from app.ml.trocr_runtime import TrocrGeneration, TrocrRuntime, TrocrRuntimeError
from app.worker.main import _OCR_OBSERVATIONS, _make_ocr_observation


def _rss_bytes() -> int | None:
    try:
        import psutil

        return int(psutil.Process().memory_info().rss)
    except (ImportError, OSError):
        return None


def _peak_vram_bytes(device: str) -> int | None:
    if not device.startswith("cuda"):
        return None
    try:
        import torch

        return int(torch.cuda.max_memory_allocated())
    except (ImportError, RuntimeError):
        return None


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1] + (left_char != right_char),
                )
            )
        previous = current
    return previous[-1]


def _cer(reference: str, hypothesis: str) -> float:
    if not reference:
        return 0.0 if not hypothesis else 1.0
    return _edit_distance(reference, hypothesis) / len(reference)


def _score_key(generation: TrocrGeneration, profile: str) -> tuple[bool, float, bool]:
    score = generation.mean_token_log_probability
    return score is not None, score if score is not None else float("-inf"), profile == "rectified_rgb"


def _rows(database_path: Path, *, limit: int) -> list[dict[str, Any]]:
    import sqlite3

    with sqlite3.connect(database_path) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            """SELECT c.storage_key,c.width,c.height,lr.raw_text,
                      r.trocr_model_version,r.rslora_adapter_version,r.device,r.dtype
               FROM recognition_line_crops c
               JOIN recognition_line_results lr ON lr.crop_id=c.id
               JOIN recognition_runs r ON r.id=c.recognition_run_id
               WHERE lr.state='completed'
                 AND r.id=(SELECT id FROM recognition_runs ORDER BY started_at DESC LIMIT 1)
               ORDER BY c.created_at,c.id LIMIT ?""",
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path("data/studio.sqlite3"))
    parser.add_argument("--storage", type=Path, default=Path("data/assets"))
    parser.add_argument("--ground-truth-json", type=Path)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--device", choices=("auto", "cpu", "cuda"), default="cpu")
    parser.add_argument("--num-beams", type=int, default=1)
    parser.add_argument("--max-new-tokens", type=int, default=32)
    arguments = parser.parse_args()
    if not 1 <= arguments.limit <= 16:
        parser.error("--limit must be between 1 and 16")
    if not 1 <= arguments.num_beams <= 4 or not 1 <= arguments.max_new_tokens <= 256:
        parser.error("generation values are outside safe bounds")
    if not arguments.database.is_file():
        parser.error("--database must be a readable SQLite database")
    truth: dict[str, str] = {}
    if arguments.ground_truth_json is not None:
        try:
            payload = json.loads(arguments.ground_truth_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, ValueError) as error:
            parser.error(f"invalid ground truth JSON: {error}")
        if not isinstance(payload, dict) or not all(isinstance(key, str) and isinstance(value, str) for key, value in payload.items()):
            parser.error("ground truth JSON must be an object of storage_key to text")
        truth = payload

    rows = _rows(arguments.database, limit=arguments.limit)
    if not rows:
        print(json.dumps({"status": "failed", "code": "no_completed_line_crops"}, ensure_ascii=True, sort_keys=True))
        return 1

    storage = FileStorage(arguments.storage)
    runtime = TrocrRuntime(
        Path(__file__).resolve().parents[1] / "models",
        device=arguments.device,
        adapter_mode="none",
    )
    started = time.perf_counter()
    before_rss = _rss_bytes()
    try:
        evidence = runtime.warmup()
        after_warmup_rss = _rss_bytes()
        records: list[dict[str, Any]] = []
        second_wins = 0
        for row in rows:
            path = storage.resolve(str(row["storage_key"]))
            with Image.open(path) as source:
                base = source.convert("RGB")
            generations: dict[str, TrocrGeneration] = {}
            durations: dict[str, int] = {}
            try:
                for profile in _OCR_OBSERVATIONS:
                    observation = _make_ocr_observation(base, profile)
                    try:
                        observation_started = time.perf_counter()
                        generations[profile] = runtime.recognize(
                            observation,
                            num_beams=arguments.num_beams,
                            max_new_tokens=arguments.max_new_tokens,
                        )
                        durations[profile] = round((time.perf_counter() - observation_started) * 1000)
                    finally:
                        observation.close()
            finally:
                base.close()
            winner_profile = max(_OCR_OBSERVATIONS, key=lambda profile: _score_key(generations[profile], profile))
            if winner_profile == _OCR_OBSERVATIONS[1]:
                second_wins += 1
            reference = truth.get(str(row["storage_key"]))
            metric = {}
            if reference is not None:
                metric = {
                    "reference_length": len(reference),
                    "cer": {profile: round(_cer(reference, generations[profile].text), 6) for profile in _OCR_OBSERVATIONS},
                    "exact_match": {profile: generations[profile].text == reference for profile in _OCR_OBSERVATIONS},
                }
            records.append(
                {
                    "storage_key": row["storage_key"],
                    "size": [row["width"], row["height"]],
                    "legacy_raw_text": row["raw_text"],
                    "legacy_model": {
                        "model_version": row["trocr_model_version"],
                        "adapter_version": row["rslora_adapter_version"],
                        "device": row["device"],
                        "dtype": row["dtype"],
                    },
                    "observations": {
                        profile: {
                            "text": generations[profile].text,
                            "confidence": generations[profile].mean_token_log_probability,
                            "generated_token_count": generations[profile].generated_token_count,
                            "duration_ms": durations[profile],
                        }
                        for profile in _OCR_OBSERVATIONS
                    },
                    "winner": winner_profile,
                    **metric,
                }
            )
    except (OSError, ValueError, TrocrRuntimeError) as error:
        print(json.dumps({"status": "failed", "code": str(error)}, ensure_ascii=True, sort_keys=True))
        return 1
    finally:
        runtime.close()

    after_rss = _rss_bytes()
    rss_samples = [value for value in (before_rss, after_warmup_rss, after_rss) if value is not None]
    payload = {
        "status": "ready",
        "mode": "base-only",
        "model_version": evidence.model_version,
        "adapter_version": evidence.adapter_version,
        "device": evidence.device,
        "dtype": evidence.dtype,
        "line_count": len(records),
        "second_observation_wins": second_wins,
        "ground_truth_count": sum("cer" in record for record in records),
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "rss_bytes": {
            "before": before_rss,
            "after_warmup": after_warmup_rss,
            "after": after_rss,
            "observed_peak": max(rss_samples) if rss_samples else None,
        },
        "peak_vram_bytes": _peak_vram_bytes(evidence.device),
        "records": records,
    }
    print(json.dumps(payload, ensure_ascii=True, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
