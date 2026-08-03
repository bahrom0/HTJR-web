from __future__ import annotations

import io
import json
import math
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from PIL import Image


KRAKEN_RUNTIME_VERSION = "kraken-sidecar-client:v1"


class KrakenRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class KrakenLine:
    id: str
    reading_order: int
    boundary: tuple[tuple[float, float], ...]
    baseline: tuple[tuple[float, float], ...]


@dataclass(frozen=True, slots=True)
class KrakenDetection:
    detector_version: str
    width: int
    height: int
    lines: tuple[KrakenLine, ...]
    duration_ms: int
    warmup_ms: int


@dataclass(frozen=True, slots=True)
class KrakenReadinessEvidence:
    model_version: str
    runtime_version: str
    kraken_version: str
    model_sha256: str
    device: str
    dtype: str
    warmup_duration_ms: int
    endpoint: str


def _json_object(payload: bytes, *, invalid_code: str) -> dict[str, Any]:
    try:
        value = json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KrakenRuntimeError(invalid_code) from exc
    if not isinstance(value, dict):
        raise KrakenRuntimeError(invalid_code)
    return value


def _number(value: object, *, invalid_code: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
        raise KrakenRuntimeError(invalid_code)
    return float(value)


def _points(value: object, *, minimum: int, invalid_code: str) -> tuple[tuple[float, float], ...]:
    if not isinstance(value, list):
        raise KrakenRuntimeError(invalid_code)
    points: list[tuple[float, float]] = []
    for raw_point in value:
        if not isinstance(raw_point, list) or len(raw_point) != 2:
            raise KrakenRuntimeError(invalid_code)
        points.append(
            (
                _number(raw_point[0], invalid_code=invalid_code),
                _number(raw_point[1], invalid_code=invalid_code),
            )
        )
    if len(points) < minimum:
        raise KrakenRuntimeError(invalid_code)
    return tuple(points)


class KrakenRuntime:
    def __init__(self, endpoint: str, *, timeout_seconds: float = 180.0) -> None:
        parsed = parse.urlsplit(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"} or parsed.query or parsed.fragment:
            raise ValueError("Kraken endpoint must be a loopback HTTP URL")
        if timeout_seconds <= 0:
            raise ValueError("Kraken timeout must be positive")
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self._evidence: KrakenReadinessEvidence | None = None

    @property
    def evidence(self) -> KrakenReadinessEvidence | None:
        return self._evidence

    def _call(self, path: str, *, body: bytes | None = None) -> dict[str, Any]:
        headers = {"Accept": "application/json"}
        method = "GET"
        if body is not None:
            headers["Content-Type"] = "image/png"
            method = "POST"
        outbound = request.Request(
            f"{self.endpoint}{path}",
            data=body,
            headers=headers,
            method=method,
        )
        try:
            with request.urlopen(outbound, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise KrakenRuntimeError("kraken_sidecar_unavailable")
                return _json_object(response.read(), invalid_code="kraken_sidecar_response_invalid")
        except KrakenRuntimeError:
            raise
        except (error.HTTPError, error.URLError, TimeoutError, OSError) as exc:
            raise KrakenRuntimeError("kraken_sidecar_unavailable") from exc

    def warmup(self) -> KrakenReadinessEvidence:
        payload = self._call("/health")
        if payload.get("status") != "ready" or not isinstance(payload.get("evidence"), dict):
            raise KrakenRuntimeError("kraken_sidecar_response_invalid")
        evidence = payload["evidence"]
        required_strings = ("model_version", "kraken_version", "model_sha256", "device", "precision")
        if any(not isinstance(evidence.get(field), str) or not evidence[field] for field in required_strings):
            raise KrakenRuntimeError("kraken_sidecar_response_invalid")
        warmup_ms = evidence.get("warmup_duration_ms")
        if not isinstance(warmup_ms, int) or warmup_ms < 0:
            raise KrakenRuntimeError("kraken_sidecar_response_invalid")
        self._evidence = KrakenReadinessEvidence(
            model_version=evidence["model_version"],
            runtime_version=KRAKEN_RUNTIME_VERSION,
            kraken_version=evidence["kraken_version"],
            model_sha256=evidence["model_sha256"],
            device=evidence["device"],
            dtype=evidence["precision"],
            warmup_duration_ms=warmup_ms,
            endpoint=self.endpoint,
        )
        return self._evidence

    def detect(self, image: Image.Image) -> KrakenDetection:
        if image.width < 1 or image.height < 1:
            raise KrakenRuntimeError("kraken_image_invalid")
        evidence = self._evidence or self.warmup()
        encoded = io.BytesIO()
        image.convert("RGB").save(encoded, format="PNG", optimize=False)
        payload = self._call("/detect", body=encoded.getvalue())
        image_size = payload.get("image_size")
        if (
            not isinstance(image_size, list)
            or len(image_size) != 2
            or not all(isinstance(value, int) and value > 0 for value in image_size)
            or image_size != [image.width, image.height]
        ):
            raise KrakenRuntimeError("kraken_sidecar_response_invalid")
        detector_version = payload.get("detector_version")
        duration_ms = payload.get("duration_ms")
        raw_lines = payload.get("lines")
        if (
            not isinstance(detector_version, str)
            or detector_version != evidence.model_version
            or not isinstance(duration_ms, int)
            or duration_ms < 0
            or not isinstance(raw_lines, list)
        ):
            raise KrakenRuntimeError("kraken_sidecar_response_invalid")

        lines: list[KrakenLine] = []
        expected_order = 0
        for raw_line in raw_lines:
            if not isinstance(raw_line, dict):
                raise KrakenRuntimeError("kraken_sidecar_response_invalid")
            line_id = raw_line.get("id")
            reading_order = raw_line.get("reading_order")
            if not isinstance(line_id, str) or not line_id or reading_order != expected_order:
                raise KrakenRuntimeError("kraken_sidecar_response_invalid")
            boundary = _points(
                raw_line.get("boundary"),
                minimum=3,
                invalid_code="kraken_sidecar_response_invalid",
            )
            baseline_value = raw_line.get("baseline")
            baseline = (
                _points(baseline_value, minimum=2, invalid_code="kraken_sidecar_response_invalid")
                if baseline_value
                else ()
            )
            for x, y in (*boundary, *baseline):
                if not 0 <= x <= image.width or not 0 <= y <= image.height:
                    raise KrakenRuntimeError("kraken_sidecar_response_invalid")
            lines.append(KrakenLine(line_id, reading_order, boundary, baseline))
            expected_order += 1

        return KrakenDetection(
            detector_version=detector_version,
            width=image.width,
            height=image.height,
            lines=tuple(lines),
            duration_ms=duration_ms,
            warmup_ms=evidence.warmup_duration_ms,
        )

    def close(self) -> None:
        # The model belongs to the WSL sidecar and is intentionally retained
        # between jobs. The Windows client owns no persistent ML allocation.
        return None
