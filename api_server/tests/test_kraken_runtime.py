from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from PIL import Image

from app.ml.kraken_runtime import KrakenRuntime
from app.worker.main import _normalised_kraken_quad


class _KrakenStubHandler(BaseHTTPRequestHandler):
    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def _send(self, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:
        assert self.path == "/health"
        self._send(
            {
                "status": "ready",
                "evidence": {
                    "model_version": "kraken-blla:test",
                    "kraken_version": "7.0.3",
                    "model_sha256": "a" * 64,
                    "device": "cuda:0",
                    "precision": "bf16-mixed",
                    "warmup_duration_ms": 12,
                },
            }
        )

    def do_POST(self) -> None:
        assert self.path == "/detect"
        payload = self.rfile.read(int(self.headers["Content-Length"]))
        assert payload.startswith(b"\x89PNG")
        self._send(
            {
                "schema_version": 1,
                "detector_version": "kraken-blla:test",
                "image_size": [100, 50],
                "duration_ms": 7,
                "lines": [
                    {
                        "id": "line-1",
                        "reading_order": 0,
                        "boundary": [[5, 10], [95, 8], [96, 24], [4, 26]],
                        "baseline": [[7, 22], [94, 20]],
                    }
                ],
            }
        )


@pytest.fixture
def kraken_endpoint() -> str:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _KrakenStubHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_kraken_client_preserves_boundary_and_baseline_coordinates(kraken_endpoint: str) -> None:
    runtime = KrakenRuntime(kraken_endpoint, timeout_seconds=2)

    detection = runtime.detect(Image.new("RGB", (100, 50), "white"))

    assert detection.detector_version == "kraken-blla:test"
    assert detection.lines[0].boundary == ((5.0, 10.0), (95.0, 8.0), (96.0, 24.0), (4.0, 26.0))
    assert detection.lines[0].baseline == ((7.0, 22.0), (94.0, 20.0))
    assert runtime.evidence is not None
    assert runtime.evidence.device == "cuda:0"


def test_kraken_boundary_is_reduced_to_valid_review_quad() -> None:
    polygon = _normalised_kraken_quad(
        ((5.0, 10.0), (50.0, 8.0), (95.0, 10.0), (96.0, 24.0), (50.0, 28.0), (4.0, 26.0)),
        width=100,
        height=50,
    )

    assert len(polygon) == 4
    assert all(0 <= point[axis] <= 1 for point in polygon for axis in ("x", "y"))


def test_kraken_client_rejects_non_loopback_endpoint() -> None:
    with pytest.raises(ValueError, match="loopback"):
        KrakenRuntime("http://example.com:8011")
