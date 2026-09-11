from __future__ import annotations

import hashlib
import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.core.settings import settings
from app.ml.kraken_runtime import KrakenDetection, KrakenLine


def image_bytes() -> bytes:
    image = Image.new("RGB", (80, 60), "white")
    output = io.BytesIO(); image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def demo_client(tmp_path, monkeypatch):
    configured = replace(settings, database_path=tmp_path / "studio.sqlite3", storage_root=tmp_path / "assets", environment="development")
    import app.main as main_module
    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as client:
        yield client


def regions(texts=("Строка первая", "Строка вторая")):
    return [
        {"id": f"line-{index}", "reading_order": index, "text": text,
         "polygon": [{"x": .1, "y": .1 + index * .3}, {"x": .9, "y": .1 + index * .3},
                     {"x": .9, "y": .2 + index * .3}, {"x": .1, "y": .2 + index * .3}]}
        for index, text in enumerate(texts)
    ]


def test_demo_preset_persists_regions_and_assembled_text(demo_client) -> None:
    digest = hashlib.sha256(image_bytes()).hexdigest()
    response = demo_client.put(f"/api/v1/demo/presets/{digest}", json={"original_filename": "page.png", "regions": regions()})
    assert response.status_code == 200
    assert response.json()["text"] == "Строка первая\nСтрока вторая"
    assert demo_client.get(f"/api/v1/demo/presets/{digest}").json()["regions"][1]["text"] == "Строка вторая"


def test_demo_rejects_missing_line_text_and_bad_order(demo_client) -> None:
    digest = "a" * 64
    missing = regions(("", "ok"))
    assert demo_client.put(f"/api/v1/demo/presets/{digest}", json={"regions": missing}).status_code == 422
    invalid = regions(); invalid[1]["reading_order"] = 3
    assert demo_client.put(f"/api/v1/demo/presets/{digest}", json={"regions": invalid}).status_code == 422


def test_find_lines_uses_kraken_output(demo_client, monkeypatch) -> None:
    class FakeKraken:
        def __init__(self, *_args, **_kwargs): pass
        def detect(self, image):
            return KrakenDetection("kraken-test", image.width, image.height, (
                KrakenLine("l1", 0, ((8, 8), (72, 8), (72, 20), (8, 20)), ((8, 18), (72, 18))),
            ), 4, 1)
    monkeypatch.setattr("app.api.v1.demo.KrakenRuntime", FakeKraken)
    response = demo_client.post("/api/v1/demo/detect-regions", content=image_bytes(), headers={"Content-Type": "image/png"})
    assert response.status_code == 200
    assert response.json()["regions"][0]["polygon"][0] == {"x": .1, "y": 8 / 60}


def test_unknown_and_invalid_hash(demo_client) -> None:
    assert demo_client.get(f"/api/v1/demo/presets/{'0' * 64}").status_code == 404
    assert demo_client.get("/api/v1/demo/presets/not-a-hash").status_code == 422
