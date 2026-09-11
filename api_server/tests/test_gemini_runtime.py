from __future__ import annotations

from io import BytesIO
import json
from urllib import error

from PIL import Image
import pytest

from app.ml.gemini_runtime import GeminiOcrRuntime, GeminiRuntimeError


class _Response:
    status = 200

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> _Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _api_payload(result: dict[str, object]) -> dict[str, object]:
    return {
        "choices": [{"message": {"content": json.dumps(result)}}],
        "provider": "Google AI Studio",
        "usage": {"prompt_tokens": 258, "completion_tokens": 12, "total_tokens": 270, "cost": 0.001},
    }


def test_recognize_crops_batches_images_and_preserves_order() -> None:
    captured: list[dict[str, object]] = []

    def urlopen(outbound: object, *, timeout: float) -> _Response:
        assert timeout == 12
        captured.append(json.loads(outbound.data))  # type: ignore[attr-defined]
        return _Response(_api_payload({"lines": [{"index": 0, "text": "  Салом  "}, {"index": 1, "text": "Ҷаҳон\nСатри дуюм"}]}))

    runtime = GeminiOcrRuntime(api_key="test", timeout_seconds=12, urlopen=urlopen)
    result = runtime.recognize_crops([Image.new("RGB", (40, 10), "white"), Image.new("RGB", (50, 10), "white")])

    assert [line.text for line in result.lines] == ["Салом", "Ҷаҳон\nСатри дуюм"]
    assert result.usage.total_tokens == 270
    assert result.usage.provider == "Google AI Studio"
    assert len(captured[0]["messages"][0]["content"]) == 5  # type: ignore[index]
    assert captured[0]["response_format"]["type"] == "json_schema"  # type: ignore[index]
    assert captured[0]["reasoning"] == {"effort": "low"}
    assert captured[0]["provider"]["sort"] == "price"  # type: ignore[index]
    assert captured[0]["provider"]["max_price"] == {"prompt": 0.4, "completion": 2.0}  # type: ignore[index]
    prompt = captured[0]["messages"][0]["content"][0]["text"]  # type: ignore[index]
    assert "ғ, ӣ, қ, ӯ, ҳ, ҷ" in prompt
    assert "ALL visible lines" in prompt
    assert "newline character \\n" in prompt


def test_detect_page_validates_normalized_boxes_and_downscales() -> None:
    response = _api_payload({
        "regions": [
            {"reading_order": 0, "box_2d": [100, 50, 180, 950], "text": "сатри якум"},
            {"reading_order": 1, "box_2d": [200, 55, 280, 940], "text": "сатри дуюм"},
        ]
    })
    runtime = GeminiOcrRuntime(api_key="test", page_max_edge=1000, urlopen=lambda *_args, **_kwargs: _Response(response))

    result = runtime.detect_page(Image.new("RGB", (2400, 1200), "white"))

    assert result.image_width == 1000
    assert result.image_height == 500
    assert result.regions[0].box_2d == (100, 50, 180, 950)
    assert result.regions[1].reading_order == 1


def test_detect_page_rejects_invalid_box() -> None:
    response = _api_payload({"regions": [{"reading_order": 0, "box_2d": [200, 50, 100, 900], "text": "x"}]})
    runtime = GeminiOcrRuntime(api_key="test", urlopen=lambda *_args, **_kwargs: _Response(response))

    with pytest.raises(GeminiRuntimeError, match="gemini_response_invalid"):
        runtime.detect_page(Image.new("RGB", (100, 100), "white"))


def test_detect_page_normalizes_one_based_reading_order() -> None:
    response = _api_payload({"regions": [
        {"reading_order": 2, "box_2d": [200, 50, 300, 900], "text": "second"},
        {"reading_order": 1, "box_2d": [100, 50, 180, 900], "text": "first"},
    ]})
    runtime = GeminiOcrRuntime(api_key="test", urlopen=lambda *_args, **_kwargs: _Response(response))

    result = runtime.detect_page(Image.new("RGB", (100, 100), "white"))

    assert [(region.reading_order, region.text) for region in result.regions] == [(0, "first"), (1, "second")]


def test_retryable_http_error_is_retried_once() -> None:
    attempts = 0

    def urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise error.HTTPError("https://example.test", 429, "rate limited", {}, BytesIO())
        return _Response(_api_payload({"lines": [{"index": 0, "text": "OK"}]}))

    runtime = GeminiOcrRuntime(api_key="test", urlopen=urlopen, retry_sleep=lambda _: None)
    result = runtime.recognize_crops([Image.new("RGB", (10, 10), "white")])

    assert attempts == 2
    assert result.lines[0].text == "OK"


def test_api_key_is_required() -> None:
    with pytest.raises(GeminiRuntimeError, match="gemini_api_key_missing"):
        GeminiOcrRuntime(api_key=None)
