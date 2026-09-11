from __future__ import annotations

import io
import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from math import atan2, ceil, floor, hypot
from uuid import uuid4

from PIL import Image, ImageOps

from app.core.database import Database
from app.core.storage import FileStorage


class RecognitionRunNotFound(Exception):
    pass


class RecognitionInputInvalid(Exception):
    pass


class ManualFallbackUnavailable(Exception):
    pass


@dataclass(frozen=True, slots=True)
class RunRegion:
    id: str
    source_region_id: str
    polygon: tuple[tuple[float, float], ...]
    reading_order: int
    flags: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class StoredCrop:
    id: str
    storage_key: str
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class LineResult:
    run_region_id: str
    state: str
    raw_text: str | None
    error_code: str | None


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _polygon_area(points: tuple[tuple[float, float], ...]) -> float:
    return 0.5 * sum(
        left[0] * right[1] - right[0] * left[1]
        for left, right in zip(points, (*points[1:], points[0]), strict=True)
    )


def _ordered_quad(points: tuple[tuple[float, float], ...]) -> tuple[tuple[float, float], ...] | None:
    if len(points) != 4 or abs(_polygon_area(points)) < 1e-8:
        return None
    center_x = sum(point[0] for point in points) / 4
    center_y = sum(point[1] for point in points) / 4
    ordered = sorted(points, key=lambda point: atan2(point[1] - center_y, point[0] - center_x))
    start = min(range(4), key=lambda index: (ordered[index][0] + ordered[index][1], ordered[index][1], ordered[index][0]))
    ordered = tuple(ordered[(start + index) % 4] for index in range(4))
    # The image-coordinate ordering must be TL, TR, BR, BL for the
    # perspective transform.  Reverse a counter-clockwise input if needed.
    if _polygon_area(ordered) < 0:
        ordered = (ordered[0], ordered[3], ordered[2], ordered[1])
    if abs(_polygon_area(ordered)) < 1e-8:
        return None
    return ordered


def _is_axis_aligned_quad(points: tuple[tuple[float, float], ...]) -> bool:
    return len(points) == 4 and all(
        abs(left[0] - right[0]) < 1e-7 or abs(left[1] - right[1]) < 1e-7
        for left, right in zip(points, (*points[1:], points[0]), strict=True)
    )


def _perspective_crop(
    image: Image.Image,
    polygon: tuple[tuple[float, float], ...],
    padding_fraction: float,
) -> Image.Image | None:
    if _is_axis_aligned_quad(polygon):
        return None
    ordered = _ordered_quad(polygon)
    if ordered is None:
        return None
    center_x = sum(point[0] for point in ordered) / 4
    center_y = sum(point[1] for point in ordered) / 4
    scale = 1.0 + 2.0 * padding_fraction
    expanded = tuple(
        (
            max(0.0, min(1.0, center_x + (point[0] - center_x) * scale)),
            max(0.0, min(1.0, center_y + (point[1] - center_y) * scale)),
        )
        for point in ordered
    )
    pixel_points = tuple((x * image.width, y * image.height) for x, y in expanded)
    top_width = hypot(pixel_points[1][0] - pixel_points[0][0], pixel_points[1][1] - pixel_points[0][1])
    bottom_width = hypot(pixel_points[2][0] - pixel_points[3][0], pixel_points[2][1] - pixel_points[3][1])
    left_height = hypot(pixel_points[3][0] - pixel_points[0][0], pixel_points[3][1] - pixel_points[0][1])
    right_height = hypot(pixel_points[2][0] - pixel_points[1][0], pixel_points[2][1] - pixel_points[1][1])
    width = max(2, round(max(top_width, bottom_width)))
    height = max(2, round(max(left_height, right_height)))
    # PIL's QUAD source order is upper-left, lower-left, lower-right,
    # upper-right; our canonical order is upper-left, upper-right,
    # lower-right, lower-left.
    source_quad = (
        pixel_points[0][0], pixel_points[0][1],
        pixel_points[3][0], pixel_points[3][1],
        pixel_points[2][0], pixel_points[2][1],
        pixel_points[1][0], pixel_points[1][1],
    )
    source = image.convert("RGB")
    try:
        return source.transform(
            (width, height),
            Image.Transform.QUAD,
            source_quad,
            resample=Image.Resampling.BICUBIC,
        )
    except (ValueError, OSError):
        return None
    finally:
        source.close()


def assess_line_crop(image: Image.Image) -> dict[str, object]:
    """Return review-only geometry/content diagnostics for one immutable crop."""
    width, height = int(image.width), int(image.height)
    aspect_ratio = width / height if height else 0.0
    sample = ImageOps.grayscale(image)
    sample.thumbnail((512, 128), Image.Resampling.BILINEAR)
    get_pixels = getattr(sample, "get_flattened_data", sample.getdata)
    pixels = list(get_pixels())
    ink_coverage = sum(pixel < 240 for pixel in pixels) / len(pixels) if pixels else 0.0
    warnings: list[str] = []
    if width < 16:
        warnings.append("width_too_small")
    if height < 16:
        warnings.append("height_too_small")
    if aspect_ratio < 0.25 or aspect_ratio > 20.0:
        warnings.append("aspect_ratio_suspicious")
    if ink_coverage < 0.005:
        warnings.append("ink_coverage_low")
    return {
        "width": width,
        "height": height,
        "aspect_ratio": round(aspect_ratio, 4),
        "ink_coverage": round(ink_coverage, 6),
        "warnings": warnings,
        "quality_warning": bool(warnings),
    }


def _crop_image(image: Image.Image, polygon: tuple[tuple[float, float], ...], padding_fraction: float) -> Image.Image:
    if not polygon:
        raise RecognitionInputInvalid("recognition_region_empty")
    xs, ys = zip(*polygon, strict=True)
    region_left, region_top = min(xs), min(ys)
    region_right, region_bottom = max(xs), max(ys)
    # `padding_fraction` is relative to the selected line, not to the whole
    # page. Using it as an absolute normalized-page offset made 0.08 add 8%
    # of the entire photograph on every side of even a tiny manual region.
    padding_x = (region_right - region_left) * padding_fraction
    padding_y = (region_bottom - region_top) * padding_fraction
    left = max(0.0, region_left - padding_x)
    top = max(0.0, region_top - padding_y)
    right = min(1.0, region_right + padding_x)
    bottom = min(1.0, region_bottom + padding_y)
    if right <= left or bottom <= top:
        raise RecognitionInputInvalid("recognition_crop_invalid")
    if image.width < 2 or image.height < 2:
        raise RecognitionInputInvalid("recognition_page_too_small")
    if len(polygon) == 4:
        oriented = _perspective_crop(image, polygon, padding_fraction)
        if oriented is not None:
            if oriented.width < 2 or oriented.height < 2:
                oriented.close()
                raise RecognitionInputInvalid("recognition_crop_too_small")
            return oriented
    pixel_left = min(image.width - 2, max(0, floor(left * image.width)))
    pixel_top = min(image.height - 2, max(0, floor(top * image.height)))
    pixel_right = min(image.width, max(pixel_left + 2, ceil(right * image.width)))
    pixel_bottom = min(image.height, max(pixel_top + 2, ceil(bottom * image.height)))
    pixel_box = (pixel_left, pixel_top, pixel_right, pixel_bottom)
    crop = image.crop(pixel_box).convert("RGB")
    if crop.width < 2 or crop.height < 2:
        raise RecognitionInputInvalid("recognition_crop_too_small")
    return crop


class RecognitionRepository:
    def __init__(self, database: Database, storage: FileStorage) -> None:
        self.database = database
        self.storage = storage

    def run_regions(self, owner_session_id: str, recognition_run_id: str) -> list[RunRegion]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """SELECT rr.id,rr.source_region_id,rr.polygon_json,rr.reading_order,rr.flags_json
                   FROM recognition_run_regions rr
                   JOIN recognition_runs r ON r.id=rr.recognition_run_id
                   JOIN recognition_jobs j ON j.id=r.job_id
                   WHERE rr.recognition_run_id=? AND j.owner_session_id=?
                   ORDER BY rr.reading_order,rr.id""",
                (recognition_run_id, owner_session_id),
            ).fetchall()
        return [
            RunRegion(
                id=row["id"],
                source_region_id=row["source_region_id"],
                polygon=tuple((float(point["x"]), float(point["y"])) for point in json.loads(row["polygon_json"])),
                reading_order=int(row["reading_order"]),
                flags=tuple(str(value) for value in json.loads(row["flags_json"])),
            )
            for row in rows
        ]

    def prepared_storage_key(self, owner_session_id: str, recognition_run_id: str) -> str:
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT a.storage_key FROM recognition_runs r
                   JOIN recognition_jobs j ON j.id=r.job_id
                   JOIN assets a ON a.id=r.prepared_asset_id AND a.state='committed'
                   WHERE r.id=? AND j.owner_session_id=?""",
                (recognition_run_id, owner_session_id),
            ).fetchone()
        if row is None:
            raise RecognitionRunNotFound(recognition_run_id)
        return str(row["storage_key"])

    def crop_for_region(
        self,
        owner_session_id: str,
        recognition_run_id: str,
        region: RunRegion,
        prepared_image: Image.Image,
        *,
        padding_fraction: float,
    ) -> StoredCrop:
        with self.database.connect() as connection:
            existing = connection.execute(
                """SELECT id,storage_key,width,height FROM recognition_line_crops
                   WHERE recognition_run_id=? AND run_region_id=? AND owner_session_id=?""",
                (recognition_run_id, region.id, owner_session_id),
            ).fetchone()
        if existing is not None:
            return StoredCrop(existing["id"], existing["storage_key"], existing["width"], existing["height"])
        crop = _crop_image(prepared_image, region.polygon, padding_fraction)
        encoded = io.BytesIO()
        crop.save(encoded, format="PNG", optimize=False, compress_level=6)
        staged = self.storage.stage(io.BytesIO(encoded.getvalue()))
        crop_id, now = str(uuid4()), _now()
        committed = False
        try:
            with self.database.transaction(immediate=True) as connection:
                run = connection.execute(
                    """SELECT 1 FROM recognition_runs r JOIN recognition_jobs j ON j.id=r.job_id
                       WHERE r.id=? AND j.owner_session_id=?""",
                    (recognition_run_id, owner_session_id),
                ).fetchone()
                if run is None:
                    raise RecognitionRunNotFound(recognition_run_id)
                existing = connection.execute(
                    "SELECT id,storage_key,width,height FROM recognition_line_crops WHERE run_region_id=?",
                    (region.id,),
                ).fetchone()
                if existing is not None:
                    self.storage.discard_temporary(staged.storage_key)
                    return StoredCrop(existing["id"], existing["storage_key"], existing["width"], existing["height"])
                self.storage.commit(staged)
                committed = True
                connection.execute(
                    """INSERT INTO recognition_line_crops(
                           id,owner_session_id,recognition_run_id,run_region_id,storage_key,sha256,byte_size,width,height,padding_fraction,created_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        crop_id, owner_session_id, recognition_run_id, region.id, staged.storage_key, staged.sha256,
                        staged.byte_size, crop.width, crop.height, padding_fraction, now,
                    ),
                )
        except sqlite3.IntegrityError:
            if committed:
                self.storage.discard_committed(staged.storage_key)
            else:
                self.storage.discard_temporary(staged.storage_key)
            with self.database.connect() as connection:
                existing = connection.execute(
                    "SELECT id,storage_key,width,height FROM recognition_line_crops WHERE run_region_id=?", (region.id,)
                ).fetchone()
            if existing is not None:
                return StoredCrop(existing["id"], existing["storage_key"], existing["width"], existing["height"])
            raise
        except BaseException:
            if committed:
                self.storage.discard_committed(staged.storage_key)
            else:
                self.storage.discard_temporary(staged.storage_key)
            raise
        return StoredCrop(crop_id, staged.storage_key, crop.width, crop.height)

    def latest_results(self, owner_session_id: str, recognition_run_id: str) -> dict[str, LineResult]:
        with self.database.connect() as connection:
            rows = connection.execute(
                """WITH ranked AS (
                     SELECT lr.*,ROW_NUMBER() OVER(PARTITION BY lr.run_region_id ORDER BY lr.line_attempt DESC) rank
                     FROM recognition_line_results lr
                     JOIN recognition_runs r ON r.id=lr.recognition_run_id
                     JOIN recognition_jobs j ON j.id=r.job_id
                     WHERE lr.recognition_run_id=? AND j.owner_session_id=?
                   ) SELECT run_region_id,state,raw_text,error_code FROM ranked WHERE rank=1""",
                (recognition_run_id, owner_session_id),
            ).fetchall()
        return {
            row["run_region_id"]: LineResult(row["run_region_id"], row["state"], row["raw_text"], row["error_code"])
            for row in rows
        }

    def _record_result(
        self,
        owner_session_id: str,
        recognition_run_id: str,
        region: RunRegion,
        crop: StoredCrop,
        *,
        state: str,
        raw_text: str | None,
        generation: dict[str, object] | None,
        duration_ms: int | None,
        error_code: str | None,
        error_retryable: bool,
    ) -> LineResult:
        now = _now()
        with self.database.transaction(immediate=True) as connection:
            owned = connection.execute(
                """SELECT 1 FROM recognition_runs r
                   JOIN recognition_jobs j ON j.id=r.job_id
                   JOIN recognition_run_regions rr ON rr.id=? AND rr.recognition_run_id=r.id
                   JOIN recognition_line_crops c ON c.id=? AND c.recognition_run_id=r.id AND c.run_region_id=rr.id
                   WHERE r.id=? AND j.owner_session_id=?""",
                (region.id, crop.id, recognition_run_id, owner_session_id),
            ).fetchone()
            if owned is None:
                raise RecognitionInputInvalid("recognition_result_input_mismatch")
            prior = connection.execute(
                "SELECT COALESCE(MAX(line_attempt),0)+1 FROM recognition_line_results WHERE recognition_run_id=? AND run_region_id=?",
                (recognition_run_id, region.id),
            ).fetchone()[0]
            connection.execute(
                """INSERT INTO recognition_line_results(
                       id,owner_session_id,recognition_run_id,run_region_id,crop_id,line_attempt,state,raw_text,
                       generation_json,duration_ms,error_code,error_retryable,created_at,updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    str(uuid4()), owner_session_id, recognition_run_id, region.id, crop.id, prior, state, raw_text,
                    json.dumps(generation, separators=(",", ":"), sort_keys=True) if generation is not None else None,
                    duration_ms, error_code, int(error_retryable), now, now,
                ),
            )
        return LineResult(region.id, state, raw_text, error_code)

    def record_success(
        self,
        owner_session_id: str,
        recognition_run_id: str,
        region: RunRegion,
        crop: StoredCrop,
        *,
        raw_text: str,
        generation: dict[str, object],
        duration_ms: int,
    ) -> LineResult:
        return self._record_result(
            owner_session_id,
            recognition_run_id,
            region,
            crop,
            state="completed",
            raw_text=raw_text,
            generation=generation,
            duration_ms=duration_ms,
            error_code=None,
            error_retryable=False,
        )

    def record_failure(
        self,
        owner_session_id: str,
        recognition_run_id: str,
        region: RunRegion,
        crop: StoredCrop,
        *,
        error_code: str,
        retryable: bool,
    ) -> LineResult:
        return self._record_result(
            owner_session_id,
            recognition_run_id,
            region,
            crop,
            state="failed_retryable" if retryable else "failed_terminal",
            raw_text=None,
            generation=None,
            duration_ms=None,
            error_code=error_code,
            error_retryable=retryable,
        )

    def record_manual_fallback(
        self,
        owner_session_id: str,
        job_id: str,
        run_region_id: str,
        *,
        raw_text: str,
    ) -> tuple[str, bool]:
        """Persist a user-supplied raw line only for an active partial run.

        This intentionally does not create confirmed text: it replaces one
        failed raw line result, records its explicit source in generation
        metadata, and lets the caller finalize the job only once every line
        has a result.
        """
        if len(raw_text) > 10_000:
            raise RecognitionInputInvalid("manual_fallback_text_too_long")
        with self.database.connect() as connection:
            row = connection.execute(
                """SELECT r.id AS run_id,rr.id AS run_region_id,rr.source_region_id,rr.polygon_json,
                          rr.reading_order,rr.flags_json,c.id AS crop_id,c.storage_key,c.width,c.height
                   FROM recognition_jobs j
                   JOIN recognition_runs r ON r.job_id=j.id AND r.finished_at IS NULL
                   JOIN recognition_run_regions rr ON rr.recognition_run_id=r.id
                   JOIN recognition_line_crops c ON c.recognition_run_id=r.id AND c.run_region_id=rr.id
                   WHERE j.id=? AND j.owner_session_id=? AND j.state='partial' AND rr.id=?""",
                (job_id, owner_session_id, run_region_id),
            ).fetchone()
        if row is None:
            raise ManualFallbackUnavailable("manual_fallback_not_available")
        run_id = str(row["run_id"])
        latest = self.latest_results(owner_session_id, run_id).get(run_region_id)
        if latest is None or latest.state == "completed":
            raise ManualFallbackUnavailable("manual_fallback_not_available")
        region = RunRegion(
            id=str(row["run_region_id"]),
            source_region_id=str(row["source_region_id"]),
            polygon=tuple((float(point["x"]), float(point["y"])) for point in json.loads(row["polygon_json"])),
            reading_order=int(row["reading_order"]),
            flags=tuple(str(value) for value in json.loads(row["flags_json"])),
        )
        crop = StoredCrop(str(row["crop_id"]), str(row["storage_key"]), int(row["width"]), int(row["height"]))
        self._record_result(
            owner_session_id,
            run_id,
            region,
            crop,
            state="completed",
            raw_text=raw_text,
            generation={"source": "manual_fallback"},
            duration_ms=None,
            error_code=None,
            error_retryable=False,
        )
        _, is_partial = self.assemble_raw_page(owner_session_id, run_id)
        return run_id, is_partial

    def assemble_raw_page(self, owner_session_id: str, recognition_run_id: str) -> tuple[str, bool]:
        with self.database.transaction(immediate=True) as connection:
            run = connection.execute(
                """SELECT j.page_id FROM recognition_runs r JOIN recognition_jobs j ON j.id=r.job_id
                   WHERE r.id=? AND j.owner_session_id=?""",
                (recognition_run_id, owner_session_id),
            ).fetchone()
            if run is None:
                raise RecognitionRunNotFound(recognition_run_id)
            rows = connection.execute(
                """WITH ranked AS (
                     SELECT lr.*,ROW_NUMBER() OVER(PARTITION BY lr.run_region_id ORDER BY lr.line_attempt DESC) rank
                     FROM recognition_line_results lr WHERE lr.recognition_run_id=?
                   )
                   SELECT rr.reading_order,ranked.state,ranked.raw_text
                   FROM recognition_run_regions rr
                   JOIN recognition_runs r ON r.id=rr.recognition_run_id
                   JOIN recognition_jobs j ON j.id=r.job_id
                   LEFT JOIN ranked ON ranked.run_region_id=rr.id AND ranked.rank=1
                   WHERE rr.recognition_run_id=? AND j.owner_session_id=?
                   ORDER BY rr.reading_order,rr.id""",
                (recognition_run_id, recognition_run_id, owner_session_id),
            ).fetchall()
            assembled: list[str] = []
            is_partial = False
            for row in rows:
                if row["state"] == "completed" and row["raw_text"] is not None:
                    assembled.append(str(row["raw_text"]))
                else:
                    is_partial = True
                    assembled.append(f"[\u041d\u0435 \u0440\u0430\u0441\u043f\u043e\u0437\u043d\u0430\u043d\u043e: \u0441\u0442\u0440\u043e\u043a\u0430 {int(row['reading_order']) + 1}]")
            raw_text = "\n".join(assembled)
            existing = connection.execute(
                "SELECT raw_text,is_partial FROM page_raw_results WHERE recognition_run_id=?", (recognition_run_id,)
            ).fetchone()
            if existing is None:
                connection.execute(
                    """INSERT INTO page_raw_results(id,owner_session_id,recognition_run_id,page_id,raw_text,is_partial,created_at)
                       VALUES (?,?,?,?,?,?,?)""",
                    (str(uuid4()), owner_session_id, recognition_run_id, run["page_id"], raw_text, int(is_partial), _now()),
                )
            else:
                connection.execute(
                    "UPDATE page_raw_results SET raw_text=?,is_partial=? WHERE recognition_run_id=?",
                    (raw_text, int(is_partial), recognition_run_id),
                )
        return raw_text, is_partial
