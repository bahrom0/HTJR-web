from __future__ import annotations

from base64 import b64encode
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from io import BytesIO
import json
from time import monotonic, sleep
from typing import Any
from urllib import error, request

from PIL import Image


_API_ENDPOINT = "https://openrouter.ai/api/v1/chat/completions"
_RETRYABLE_STATUS_CODES = {429, 500, 502, 503, 504}


class GeminiRuntimeError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class GeminiUsage:
    prompt_tokens: int
    output_tokens: int
    total_tokens: int
    cost_usd: float | None = None
    provider: str | None = None


@dataclass(frozen=True, slots=True)
class GeminiLineGeneration:
    index: int
    text: str


@dataclass(frozen=True, slots=True)
class GeminiPageRegion:
    reading_order: int
    box_2d: tuple[int, int, int, int]
    text: str


@dataclass(frozen=True, slots=True)
class GeminiReadinessEvidence:
    model_version: str
    runtime_version: str
    model_sha256: str | None
    device: str
    dtype: str
    warmup_duration_ms: int
    endpoint: str


@dataclass(frozen=True, slots=True)
class GeminiLineResult:
    lines: tuple[GeminiLineGeneration, ...]
    usage: GeminiUsage
    duration_ms: int


@dataclass(frozen=True, slots=True)
class GeminiPageResult:
    regions: tuple[GeminiPageRegion, ...]
    usage: GeminiUsage
    duration_ms: int
    image_width: int
    image_height: int
    detector_version: str


def _encode_png(image: Image.Image, *, max_edge: int | None = None) -> tuple[str, int, int]:
    if image.width < 1 or image.height < 1:
        raise GeminiRuntimeError("gemini_image_invalid")
    prepared = image.convert("RGB")
    try:
        if max_edge is not None and max(prepared.size) > max_edge:
            prepared.thumbnail((max_edge, max_edge), Image.Resampling.LANCZOS)
        encoded = BytesIO()
        prepared.save(encoded, format="PNG", optimize=True)
        return b64encode(encoded.getvalue()).decode("ascii"), prepared.width, prepared.height
    finally:
        prepared.close()


def _usage(payload: dict[str, Any]) -> GeminiUsage:
    raw = payload.get("usage")
    if not isinstance(raw, dict):
        return GeminiUsage(0, 0, 0)

    def count(name: str) -> int:
        value = raw.get(name, 0)
        return value if isinstance(value, int) and value >= 0 else 0

    return GeminiUsage(
        count("prompt_tokens"),
        count("completion_tokens"),
        count("total_tokens"),
        float(raw["cost"]) if isinstance(raw.get("cost"), (int, float)) else None,
        payload.get("provider") if isinstance(payload.get("provider"), str) else None,
    )


def _response_object(payload: dict[str, Any]) -> dict[str, Any]:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise GeminiRuntimeError("gemini_response_empty")
    message = choices[0].get("message")
    text = message.get("content") if isinstance(message, dict) else None
    if not isinstance(text, str):
        raise GeminiRuntimeError("gemini_response_invalid")
    text = text.strip()
    if not text:
        raise GeminiRuntimeError("gemini_response_empty")
    if text.startswith("```"):
        first_newline = text.find("\n")
        text = text[first_newline + 1:] if first_newline >= 0 else text
        if text.endswith("```"):
            text = text[:-3].rstrip()
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError as exc:
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise GeminiRuntimeError("gemini_response_invalid") from exc
        try:
            decoded = json.loads(text[start:end + 1])
        except json.JSONDecodeError as nested:
            raise GeminiRuntimeError("gemini_response_invalid") from nested
    if not isinstance(decoded, dict):
        raise GeminiRuntimeError("gemini_response_invalid")
    return decoded


class GeminiOcrRuntime:
    def __init__(
        self,
        *,
        api_key: str | None,
        model: str = "google/gemini-3.8-flash:floor",
        timeout_seconds: float = 120.0,
        thinking_level: str = "low",
        max_output_tokens: int = 4096,
        max_page_regions: int = 200,
        page_max_edge: int = 2000,
        max_prompt_price: float = 0.4,
        max_completion_price: float = 2.0,
        urlopen: Callable[..., Any] = request.urlopen,
        retry_sleep: Callable[[float], None] = sleep,
    ) -> None:
        if not api_key:
            raise GeminiRuntimeError("gemini_api_key_missing")
        if thinking_level not in {"low", "medium", "high"}:
            raise ValueError("thinking_level must be low, medium, or high")
        self._api_key = api_key
        self.model = model
        self.timeout_seconds = timeout_seconds
        self.thinking_level = thinking_level
        self.max_output_tokens = max_output_tokens
        self.max_page_regions = max_page_regions
        self.page_max_edge = page_max_edge
        self.max_prompt_price = max_prompt_price
        self.max_completion_price = max_completion_price
        self._urlopen = urlopen
        self._retry_sleep = retry_sleep
        self._evidence = GeminiReadinessEvidence(
            model.removesuffix(":floor"),
            "openrouter-client:v1",
            None,
            "cloud",
            "provider_managed",
            0,
            _API_ENDPOINT,
        )

    @property
    def evidence(self) -> GeminiReadinessEvidence:
        return self._evidence

    def warmup(self) -> GeminiReadinessEvidence:
        """Validate local configuration without spending tokens on a probe."""
        return self._evidence

    def _generate(
        self,
        *,
        parts: list[dict[str, Any]],
        schema: dict[str, Any],
        structured: bool = True,
    ) -> dict[str, Any]:
        content: list[dict[str, Any]] = []
        for part in parts:
            if isinstance(part.get("text"), str):
                content.append({"type": "text", "text": part["text"]})
                continue
            inline = part.get("inlineData")
            if isinstance(inline, dict) and isinstance(inline.get("data"), str):
                mime_type = inline.get("mimeType", "image/png")
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime_type};base64,{inline['data']}"},
                })
        if not structured:
            content.insert(0, {
                "type": "text",
                "text": (
                    "Return one strictly valid JSON object matching this JSON Schema. "
                    "Do not use Markdown fences, comments, labels, or any text outside the JSON object: "
                    + json.dumps(schema, separators=(",", ":"))
                ),
            })
        request_body: dict[str, Any] = {
            "model": self.model,
            "messages": [{"role": "user", "content": content}],
            "max_tokens": self.max_output_tokens,
            "reasoning": {"effort": self.thinking_level},
            "provider": {
                "sort": "price",
                "allow_fallbacks": True,
                "require_parameters": structured,
                "max_price": {
                    "prompt": self.max_prompt_price,
                    "completion": self.max_completion_price,
                },
            },
        }
        if structured:
            request_body["response_format"] = {
                    "type": "json_schema",
                    "json_schema": {"name": "tajik_htr", "strict": True, "schema": schema},
            }
        body = json.dumps(request_body, separators=(",", ":")).encode("utf-8")
        outbound = request.Request(
            _API_ENDPOINT,
            data=body,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self._api_key}",
                "HTTP-Referer": "http://localhost",
                "X-Title": "Tajik HTR Studio",
            },
            method="POST",
        )
        for attempt in range(2):
            try:
                with self._urlopen(outbound, timeout=self.timeout_seconds) as response:
                    if response.status != 200:
                        raise GeminiRuntimeError("gemini_api_unavailable")
                    payload = json.loads(response.read())
                    if not isinstance(payload, dict):
                        raise GeminiRuntimeError("gemini_response_invalid")
                    return payload
            except error.HTTPError as exc:
                if attempt == 0 and exc.code in _RETRYABLE_STATUS_CODES:
                    self._retry_sleep(0.25)
                    continue
                if exc.code in {401, 402, 403}:
                    raise GeminiRuntimeError("gemini_api_unauthorized") from exc
                if exc.code == 400:
                    try:
                        error_payload = json.loads(exc.read())
                        provider_error = error_payload.get("error", {})
                        detail = provider_error.get("message", "")
                        metadata = provider_error.get("metadata", {})
                        provider_detail = metadata.get("raw", "") if isinstance(metadata, dict) else ""
                        if provider_detail:
                            detail = f"{detail}: {provider_detail}"
                    except (AttributeError, json.JSONDecodeError, OSError):
                        detail = ""
                    safe_detail = " ".join(detail.split())[:500]
                    suffix = f":{safe_detail}" if safe_detail else ""
                    if structured and "INVALID_ARGUMENT" in provider_detail:
                        return self._generate(parts=parts, schema=schema, structured=False)
                    raise GeminiRuntimeError(f"gemini_request_invalid{suffix}") from exc
                if exc.code == 429:
                    raise GeminiRuntimeError("gemini_api_rate_limited") from exc
                raise GeminiRuntimeError("gemini_api_unavailable") from exc
            except GeminiRuntimeError:
                raise
            except (error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
                if attempt == 0:
                    self._retry_sleep(0.25)
                    continue
                raise GeminiRuntimeError("gemini_api_unavailable") from exc
        raise GeminiRuntimeError("gemini_api_unavailable")

    def recognize_crops(self, images: Sequence[Image.Image]) -> GeminiLineResult:
        if not images:
            return GeminiLineResult((), GeminiUsage(0, 0, 0), 0)
        parts: list[dict[str, Any]] = [{
            "text": (
                "Transcribe every supplied image region as Tajik Cyrillic text. A region may contain one or "
                "several text lines: transcribe ALL visible lines from top to bottom and join lines with the "
                "newline character \\n inside the text value. Never omit a second line. Use the Tajik letters "
                "ғ, ӣ, қ, ӯ, ҳ, ҷ whenever they are present; do not replace them with г, и, к, у, х, ж. "
                "Preserve punctuation, spelling, digits, and paragraph line breaks. Never invent unreadable text. "
                "Return one item for every image region, in input order, using zero-based index. Output JSON only."
            )
        }]
        for index, image in enumerate(images):
            encoded, _, _ = _encode_png(image)
            parts.extend((
                {"text": f"line_index={index}"},
                {"inlineData": {"mimeType": "image/png", "data": encoded}},
            ))
        schema = {
            "type": "object",
            "properties": {
                "lines": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {"index": {"type": "integer"}, "text": {"type": "string"}},
                        "required": ["index", "text"],
                    },
                }
            },
            "required": ["lines"],
        }
        started = monotonic()
        payload = self._generate(parts=parts, schema=schema)
        decoded = _response_object(payload)
        raw_lines = decoded.get("lines")
        if not isinstance(raw_lines, list) or len(raw_lines) != len(images):
            raise GeminiRuntimeError("gemini_line_count_mismatch")
        lines: list[GeminiLineGeneration] = []
        for expected, item in enumerate(raw_lines):
            if not isinstance(item, dict) or item.get("index") != expected or not isinstance(item.get("text"), str):
                raise GeminiRuntimeError("gemini_response_invalid")
            lines.append(GeminiLineGeneration(expected, item["text"].strip()))
        return GeminiLineResult(tuple(lines), _usage(payload), round((monotonic() - started) * 1000))

    def detect_page(self, image: Image.Image) -> GeminiPageResult:
        encoded, width, height = _encode_png(image, max_edge=self.page_max_edge)
        parts = [
            {
                "text": (
                    "Find every visible handwritten or printed Tajik text line on this document page and "
                    "transcribe it. Use the Tajik Cyrillic letters ғ, ӣ, қ, ӯ, ҳ, ҷ whenever they are present; "
                    "do not replace them with the Russian letters г, и, к, у, х, ж. "
                    "Return tight line-level boxes as [ymin,xmin,ymax,xmax], normalized to integers 0..1000. "
                    "Use natural reading order from top to bottom. Exclude decorations and never invent unreadable text. "
                    "Output JSON only."
                )
            },
            {"inlineData": {"mimeType": "image/png", "data": encoded}},
        ]
        schema = {
            "type": "object",
            "properties": {
                "regions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "reading_order": {"type": "integer"},
                            "box_2d": {
                                "type": "array",
                                "items": {"type": "integer"},
                            },
                            "text": {"type": "string"},
                        },
                        "required": ["reading_order", "box_2d", "text"],
                    },
                }
            },
            "required": ["regions"],
        }
        started = monotonic()
        payload = self._generate(parts=parts, schema=schema)
        decoded = _response_object(payload)
        raw_regions = decoded.get("regions")
        if not isinstance(raw_regions, list) or len(raw_regions) > self.max_page_regions:
            raise GeminiRuntimeError("gemini_response_invalid")
        if not all(isinstance(item, dict) and isinstance(item.get("reading_order"), int) for item in raw_regions):
            raise GeminiRuntimeError("gemini_response_invalid")
        ordered_regions = sorted(raw_regions, key=lambda item: item["reading_order"])
        regions: list[GeminiPageRegion] = []
        for expected, item in enumerate(ordered_regions):
            if expected and item["reading_order"] == ordered_regions[expected - 1]["reading_order"]:
                raise GeminiRuntimeError("gemini_response_invalid")
            box = item.get("box_2d")
            text = item.get("text")
            if (
                not isinstance(box, list)
                or len(box) != 4
                or not all(isinstance(value, int) and 0 <= value <= 1000 for value in box)
                or box[0] >= box[2]
                or box[1] >= box[3]
                or not isinstance(text, str)
            ):
                raise GeminiRuntimeError("gemini_response_invalid")
            regions.append(GeminiPageRegion(expected, tuple(box), text.strip()))
        return GeminiPageResult(
            tuple(regions),
            _usage(payload),
            round((monotonic() - started) * 1000),
            width,
            height,
            self.model.removesuffix(":floor"),
        )

    def detect(self, image: Image.Image) -> GeminiPageResult:
        return self.detect_page(image)

    def close(self) -> None:
        self._api_key = ""
