from __future__ import annotations

import argparse
import hashlib
import io
import json
import logging
import threading
import time
from dataclasses import asdict, dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import metadata, resources
from pathlib import Path
from typing import Any

from PIL import Image, UnidentifiedImageError
from kraken.configs import SegmentationInferenceConfig
from kraken.tasks import SegmentationTaskModel


LOGGER = logging.getLogger("kraken_sidecar")
SCHEMA_VERSION = 1


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _points(value: object) -> list[list[int]]:
    if not isinstance(value, (list, tuple)):
        return []
    points: list[list[int]] = []
    for point in value:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            continue
        x, y = point
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            points.append([round(x), round(y)])
    if len(points) > 1 and points[0] == points[-1]:
        points.pop()
    return points


@dataclass(frozen=True, slots=True)
class SidecarEvidence:
    schema_version: int
    service: str
    kraken_version: str
    model_version: str
    model_sha256: str
    device: str
    precision: str
    warmup_duration_ms: int


class KrakenDetector:
    def __init__(self, *, model_path: Path | None, device: str, precision: str) -> None:
        default_model = Path(resources.files("kraken").joinpath("blla.mlmodel"))
        self.model_path = (model_path or default_model).resolve()
        if not self.model_path.is_file():
            raise FileNotFoundError(f"Kraken segmentation model is missing: {self.model_path}")
        self.device = device
        self.precision = precision
        if device == "cuda:0":
            accelerator = "cuda"
            accelerator_device = 1
        elif device == "cpu":
            accelerator = "cpu"
            accelerator_device = 1
        else:
            raise ValueError(f"Unsupported Kraken device: {device}")
        self._lock = threading.Lock()
        started = time.perf_counter()
        self._model = SegmentationTaskModel.load_model(self.model_path)
        self._config = SegmentationInferenceConfig(
            accelerator=accelerator,
            device=accelerator_device,
            precision=precision,
            batch_size=1,
            num_threads=1,
            raise_on_error=True,
            text_direction="horizontal-lr",
        )
        with self._lock:
            self._model.predict(Image.new("RGB", (256, 256), "white"), self._config)
        warmup_duration_ms = round((time.perf_counter() - started) * 1000)
        model_digest = _sha256(self.model_path)
        self.evidence = SidecarEvidence(
            schema_version=SCHEMA_VERSION,
            service="kraken-line-segmentation",
            kraken_version=metadata.version("kraken"),
            model_version=f"kraken-blla:{model_digest[:12]}",
            model_sha256=model_digest,
            device=device,
            precision=precision,
            warmup_duration_ms=warmup_duration_ms,
        )

    def detect(self, image: Image.Image) -> dict[str, object]:
        source = image.convert("RGB")
        started = time.perf_counter()
        with self._lock:
            segmentation = self._model.predict(source, self._config)
        duration_ms = round((time.perf_counter() - started) * 1000)
        lines: list[dict[str, object]] = []
        for order, line in enumerate(segmentation.lines or []):
            boundary = _points(getattr(line, "boundary", None))
            baseline = _points(getattr(line, "baseline", None))
            if len(boundary) < 3:
                LOGGER.warning("Skipping Kraken line without a valid boundary: %s", getattr(line, "id", order))
                continue
            lines.append(
                {
                    "id": str(getattr(line, "id", order)),
                    "reading_order": order,
                    "boundary": boundary,
                    "baseline": baseline,
                }
            )
        return {
            "schema_version": SCHEMA_VERSION,
            "detector_version": self.evidence.model_version,
            "image_size": [source.width, source.height],
            "duration_ms": duration_ms,
            "lines": lines,
        }


class KrakenServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address: tuple[str, int], detector: KrakenDetector, max_request_bytes: int) -> None:
        super().__init__(address, KrakenRequestHandler)
        self.detector = detector
        self.max_request_bytes = max_request_bytes


class KrakenRequestHandler(BaseHTTPRequestHandler):
    server: KrakenServer

    def log_message(self, format: str, *args: Any) -> None:
        LOGGER.info("%s - %s", self.address_string(), format % args)

    def _json(self, status: HTTPStatus, payload: dict[str, object]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path != "/health":
            self._json(HTTPStatus.NOT_FOUND, {"code": "not_found"})
            return
        self._json(HTTPStatus.OK, {"status": "ready", "evidence": asdict(self.server.detector.evidence)})

    def do_POST(self) -> None:
        if self.path == "/shutdown":
            self._json(HTTPStatus.OK, {"status": "stopping"})
            threading.Thread(target=self.server.shutdown, daemon=True).start()
            return
        if self.path != "/detect":
            self._json(HTTPStatus.NOT_FOUND, {"code": "not_found"})
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            content_length = 0
        if content_length < 1 or content_length > self.server.max_request_bytes:
            self._json(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, {"code": "kraken_image_size_invalid"})
            return
        payload = self.rfile.read(content_length)
        try:
            with Image.open(io.BytesIO(payload)) as image:
                image.load()
                result = self.server.detector.detect(image)
        except (UnidentifiedImageError, OSError, ValueError):
            LOGGER.exception("Kraken failed to decode or segment an image")
            self._json(HTTPStatus.UNPROCESSABLE_ENTITY, {"code": "kraken_detection_failed"})
            return
        except Exception:
            LOGGER.exception("Kraken detector failed")
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"code": "kraken_detection_failed"})
            return
        self._json(HTTPStatus.OK, result)


def _parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Local Kraken line-segmentation sidecar")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8011)
    parser.add_argument("--model", type=Path)
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--precision", default="bf16-mixed")
    parser.add_argument("--max-request-bytes", type=int, default=30 * 1024 * 1024)
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    arguments = _parse_arguments()
    detector = KrakenDetector(
        model_path=arguments.model,
        device=arguments.device,
        precision=arguments.precision,
    )
    server = KrakenServer((arguments.host, arguments.port), detector, arguments.max_request_bytes)
    LOGGER.info(
        "Kraken sidecar ready at http://%s:%s model=%s device=%s",
        arguments.host,
        arguments.port,
        detector.evidence.model_version,
        detector.evidence.device,
    )
    try:
        server.serve_forever(poll_interval=0.25)
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
