from __future__ import annotations

import hashlib
import io
from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw, ImageFilter, ImageFont

from app.core.settings import settings
from app.core.storage import FileStorage


def image_bytes(size=(1200, 1600), *, value=242, image_format="PNG", blur=False, rotate=0, tajik=False) -> bytes:
    image = Image.new("RGB", size, (value, value, value))
    draw = ImageDraw.Draw(image)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/arial.ttf", 34)
    except OSError:
        font = ImageFont.load_default()
    for y in range(140, size[1] - 100, 90):
        text = "Тоҷикистон — забони тоҷикӣ Ғ Ӣ Қ Ӯ Ҳ Ҷ" if tajik else "Tajik HTR handwritten page"
        try:
            draw.text((100, y), text, fill=(22, 22, 22), font=font)
        except UnicodeEncodeError:
            draw.line((100, y, size[0] - 100, y + 8), fill=(22, 22, 22), width=5)
    if blur:
        image = image.filter(ImageFilter.GaussianBlur(8))
    if rotate:
        image = image.rotate(rotate, expand=True, fillcolor=(value, value, value))
    output = io.BytesIO()
    image.save(output, format=image_format, quality=90)
    return output.getvalue()


def exif_oriented_jpeg() -> bytes:
    image = Image.new("RGB", (120, 240), "white")
    ImageDraw.Draw(image).line((10, 30, 110, 30), fill="black", width=5)
    exif = image.getexif(); exif[274] = 6
    output = io.BytesIO(); image.save(output, format="JPEG", exif=exif)
    return output.getvalue()


def transparent_handwriting_png() -> bytes:
    image = Image.new("RGBA", (160, 80), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.line((25, 40, 130, 40), fill=(22, 22, 22, 255), width=7)
    output = io.BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


@pytest.fixture
def client(tmp_path, monkeypatch):
    configured = replace(settings, database_path=tmp_path / "studio.sqlite3", storage_root=tmp_path / "assets")
    import app.main as main_module
    monkeypatch.setattr(main_module, "settings", configured)
    with TestClient(main_module.create_app()) as current:
        code, _ = current.app.state.access.issue_code("upload-tests")
        exchange = current.post("/api/v1/access/exchange-code", json={"code": code})
        assert exchange.status_code == 200
        yield current, exchange.json()["csrf_token"], configured


def upload(client: TestClient, csrf: str, data: bytes, *, key="upload-test-key-0001", content_type="image/png", filename="C%3A%5Cfakepath%5C%D1%80%D1%83%D0%BA%D0%BE%D0%BF%D0%B8%D1%81%D1%8C.png"):
    return client.post("/api/v1/documents", content=data, headers={"Content-Type": content_type, "X-CSRF-Token": csrf, "Idempotency-Key": key, "X-Original-Filename": filename})


def test_real_upload_is_atomic_idempotent_and_does_not_leak_filename(client) -> None:
    current, csrf, configured = client
    data = image_bytes(tajik=True)
    first = upload(current, csrf, data)
    assert first.status_code == 201
    duplicate = upload(current, csrf, data)
    assert duplicate.status_code == 201 and duplicate.json()["duplicate"] is True
    assert duplicate.json()["document_id"] == first.json()["document_id"]
    with current.app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 1
        row = connection.execute("SELECT storage_key,original_filename,sha256 FROM assets WHERE kind='original'").fetchone()
    assert "рукопись.png" == row["original_filename"]
    assert "рукопись" not in row["storage_key"] and "fakepath" not in row["storage_key"]
    stored = current.app.state.storage.resolve(row["storage_key"])
    assert stored.is_relative_to(configured.storage_root.resolve())
    assert stored.read_bytes() == data and row["sha256"] == hashlib.sha256(data).hexdigest()


@pytest.mark.parametrize(
    ("data", "content_type", "code"),
    [
        (b"not-an-image", "image/png", "unsupported_image_type"),
        (image_bytes() + b"PK\x03\x04payload", "image/png", "image_container_invalid"),
        (image_bytes(image_format="JPEG"), "image/png", "image_type_mismatch"),
    ],
    ids=["malformed", "polyglot", "type-mismatch"],
)
def test_malformed_polyglot_and_type_mismatch_are_rejected(client, data, content_type, code) -> None:
    current, csrf, _ = client
    response = upload(current, csrf, data, key=f"validation-key-{code}", content_type=content_type)
    assert response.status_code in (415, 422)
    assert response.json()["code"] == code
    with current.app.state.database.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM documents").fetchone()[0] == 0


def test_byte_and_pixel_limits_are_enforced_without_commits(client) -> None:
    current, csrf, _ = client
    denied = current.post("/api/v1/documents", content=image_bytes(size=(50, 50)), headers={"Content-Type": "image/png", "Idempotency-Key": "csrf-required-key-01"})
    assert denied.status_code == 401 and denied.json()["code"] == "access_denied"
    current.app.state.settings = replace(current.app.state.settings, upload_max_bytes=100)
    oversized = upload(current, csrf, image_bytes(size=(100, 100)), key="oversized-byte-key-01")
    assert oversized.status_code == 413 and oversized.json()["code"] == "upload_too_large"
    current.app.state.settings = replace(current.app.state.settings, upload_max_bytes=25 * 1024 * 1024)
    huge_header = image_bytes(size=(12_001, 1))
    huge = upload(current, csrf, huge_header, key="huge-pixel-key-0001")
    assert huge.status_code == 413 and huge.json()["code"] in {"image_pixel_limit_exceeded", "image_decompression_limit"}


def test_interrupted_stream_removes_temporary_file(tmp_path) -> None:
    import asyncio
    storage = FileStorage(tmp_path / "assets")
    async def broken_stream():
        yield b"partial"
        raise ConnectionError("client disconnected")
    with pytest.raises(ConnectionError):
        asyncio.run(storage.stage_stream(broken_stream(), max_bytes=1024))
    assert list(storage.temporary.rglob("*.*")) == []


def test_preprocessing_is_reproducible_immutable_and_preview_is_owned(client) -> None:
    current, csrf, _ = client
    original = image_bytes(size=(1300, 1700), rotate=5, tajik=True)
    created = upload(current, csrf, original, key="preprocess-key-00001").json()
    page_id = created["page_id"]
    recipe = {"rotation_degrees": 90, "crop": {"x": .05, "y": .05, "width": .9, "height": .9}, "perspective": [{"x": .01, "y": .02}, {"x": .98, "y": .01}, {"x": .97, "y": .99}, {"x": .02, "y": .98}], "max_edge": 1400}
    prepared = current.post(f"/api/v1/pages/{page_id}/prepare", json=recipe, headers={"X-CSRF-Token": csrf})
    assert prepared.status_code == 200, prepared.text
    again = current.post(f"/api/v1/pages/{page_id}/prepare", json=recipe, headers={"X-CSRF-Token": csrf})
    assert again.status_code == 200 and again.json()["duplicate"] is True
    assert again.json()["recipe_hash"] == prepared.json()["recipe_hash"]
    assert again.json()["prepared_asset"]["id"] == prepared.json()["prepared_asset"]["id"]
    assert prepared.json()["pipeline_version"] == "preprocess-v1"
    assert prepared.json()["quality_threshold_version"] == "quality-v1"
    assert {"blur_laplacian_variance", "exposure_mean", "contrast_stddev", "skew_degrees", "short_edge"} <= prepared.json()["quality_metrics"].keys()
    with current.app.state.database.connect() as connection:
        source = connection.execute("SELECT storage_key FROM assets WHERE id=?", (created["asset"]["id"],)).fetchone()
    assert current.app.state.storage.resolve(source["storage_key"]).read_bytes() == original
    preview = current.get(prepared.json()["prepared_asset"]["preview_url"] + "?max_edge=99999")
    assert preview.status_code == 200 and preview.headers["content-type"] == "image/jpeg"
    assert preview.headers["cache-control"].startswith("private") and "nosniff" in preview.headers["x-content-type-options"]
    with Image.open(io.BytesIO(preview.content)) as image:
        assert max(image.size) <= current.app.state.settings.preview_max_edge
    cached = current.get(prepared.json()["prepared_asset"]["preview_url"] + "?max_edge=99999", headers={"If-None-Match": preview.headers["etag"]})
    assert cached.status_code == 304
    other_code, _ = current.app.state.access.issue_code("other-owner")
    other_exchange = current.post("/api/v1/access/exchange-code", json={"code": other_code})
    assert other_exchange.status_code == 200
    isolated = current.get(prepared.json()["prepared_asset"]["preview_url"])
    assert isolated.status_code == 404 and isolated.json()["code"] == "asset_not_found"


def test_preparation_state_confirmation_and_job_gate(client) -> None:
    current, csrf, _ = client
    created = upload(current, csrf, image_bytes(), key="preparation-confirm-key-01").json()
    page_id = created["page_id"]
    before = current.get(f"/api/v1/pages/{page_id}/preparation")
    assert before.status_code == 200
    assert before.json()["prepared_asset"] is None and before.json()["confirmed"] is False

    prepared = current.post(
        f"/api/v1/pages/{page_id}/prepare",
        json={"rotation_degrees": 90},
        headers={"X-CSRF-Token": csrf},
    )
    assert prepared.status_code == 200
    state = current.get(f"/api/v1/pages/{page_id}/preparation")
    assert state.status_code == 200
    assert state.json()["recipe_hash"] == prepared.json()["recipe_hash"]
    assert state.json()["confirmed"] is False

    rejected = current.post(
        f"/api/v1/pages/{page_id}/recognition-jobs",
        json={},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "preparation-job-gate-0001"},
    )
    assert rejected.status_code == 409
    assert rejected.json()["code"] == "page_preparation_not_confirmed"

    stale = current.post(
        f"/api/v1/pages/{page_id}/preparation/confirm",
        json={"revision": state.json()["revision"] - 1},
        headers={"X-CSRF-Token": csrf},
    )
    assert stale.status_code == 409 and stale.json()["code"] == "revision_conflict"
    confirmed = current.post(
        f"/api/v1/pages/{page_id}/preparation/confirm",
        json={"revision": state.json()["revision"]},
        headers={"X-CSRF-Token": csrf},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["recipe_hash"] == prepared.json()["recipe_hash"]
    final_state = current.get(f"/api/v1/pages/{page_id}/preparation")
    assert final_state.json()["confirmed"] is True
    created_job = current.post(
        f"/api/v1/pages/{page_id}/recognition-jobs",
        json={},
        headers={"X-CSRF-Token": csrf, "Idempotency-Key": "preparation-job-gate-0002"},
    )
    assert created_job.status_code == 201

    changed = current.post(
        f"/api/v1/pages/{page_id}/prepare",
        json={"rotation_degrees": 180},
        headers={"X-CSRF-Token": csrf},
    )
    assert changed.status_code == 200
    after_change = current.get(f"/api/v1/pages/{page_id}/preparation")
    assert after_change.json()["confirmed"] is False


def test_exif_orientation_is_applied_only_to_prepared_asset(client) -> None:
    current, csrf, _ = client
    original = exif_oriented_jpeg()
    created = upload(current, csrf, original, key="exif-orientation-key-01", content_type="image/jpeg", filename="phone.jpg").json()
    assert (created["asset"]["width"], created["asset"]["height"]) == (120, 240)
    prepared = current.post(f"/api/v1/pages/{created['page_id']}/prepare", json={"max_edge": 512}, headers={"X-CSRF-Token": csrf})
    assert prepared.status_code == 200
    assert (prepared.json()["prepared_asset"]["width"], prepared.json()["prepared_asset"]["height"]) == (240, 120)
    with current.app.state.database.connect() as connection:
        source_key = connection.execute("SELECT storage_key FROM assets WHERE id=?", (created["asset"]["id"],)).fetchone()[0]
    assert current.app.state.storage.resolve(source_key).read_bytes() == original


def test_transparent_png_is_prepared_on_white_not_black_background(client) -> None:
    current, csrf, _ = client
    created = upload(current, csrf, transparent_handwriting_png(), key="transparent-paper-key-01").json()
    prepared = current.post(
        f"/api/v1/pages/{created['page_id']}/prepare",
        json={"max_edge": 512},
        headers={"X-CSRF-Token": csrf},
    )
    assert prepared.status_code == 200
    with current.app.state.database.connect() as connection:
        storage_key = connection.execute(
            "SELECT storage_key FROM assets WHERE id=?",
            (prepared.json()["prepared_asset"]["id"],),
        ).fetchone()[0]
    with Image.open(current.app.state.storage.resolve(storage_key)) as image:
        assert image.mode == "RGB"
        assert image.getpixel((0, 0)) == (255, 255, 255)
        assert max(image.getpixel((80, 40))) < 80


@pytest.mark.parametrize(
    ("fixture", "expected_warning"),
    [
        (lambda: image_bytes(value=20), "image_too_dark"),
        (lambda: image_bytes(blur=True), "image_blurry"),
        (lambda: image_bytes(size=(500, 700)), "image_resolution_low"),
    ],
)
def test_honest_quality_warning_fixtures(client, fixture, expected_warning) -> None:
    current, csrf, _ = client
    created = upload(current, csrf, fixture(), key=f"quality-{expected_warning}-key").json()
    result = current.post(f"/api/v1/pages/{created['page_id']}/prepare", json={}, headers={"X-CSRF-Token": csrf})
    assert result.status_code == 200, result.text
    assert expected_warning in result.json()["quality_warnings"]


def test_large_and_rotated_tajik_fixtures_are_bounded(client) -> None:
    current, csrf, _ = client
    for index, data in enumerate((image_bytes(size=(2600, 1900), tajik=True), image_bytes(size=(1400, 1800), rotate=8, tajik=True))):
        created = upload(current, csrf, data, key=f"large-rotated-tajik-{index}").json()
        result = current.post(f"/api/v1/pages/{created['page_id']}/prepare", json={"max_edge": 1200}, headers={"X-CSRF-Token": csrf})
        assert result.status_code == 200
        assert max(result.json()["prepared_asset"]["width"], result.json()["prepared_asset"]["height"]) <= 1200
        if index == 1:
            assert abs(result.json()["quality_metrics"]["skew_degrees"]) >= 7
            assert "image_skewed" in result.json()["quality_warnings"]
