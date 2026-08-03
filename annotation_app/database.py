from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from math import ceil, cos, isfinite, radians, sin
from pathlib import Path
from typing import Any, Iterator, Sequence

from PIL import Image, ImageOps


IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".tif", ".tiff", ".bmp", ".webp"}


def correction_parameters(metadata: dict[str, Any]) -> tuple[int, float, float]:
    orientation = int(metadata.get("orientation_degrees", 0)) % 360
    if orientation not in {0, 90, 180, 270}:
        raise ValueError("invalid_orientation_degrees")
    deskew = float(metadata.get("deskew_degrees", 0.0))
    if not isfinite(deskew) or not -15.0 <= deskew <= 15.0:
        raise ValueError("invalid_deskew_degrees")
    return orientation, deskew, orientation + deskew


def corrected_dimensions(width: float, height: float, metadata: dict[str, Any]) -> tuple[int, int]:
    _, _, angle = correction_parameters(metadata)
    normalized = angle % 180
    if abs(normalized) < 1e-9:
        return max(1, round(width)), max(1, round(height))
    if abs(normalized - 90) < 1e-9:
        return max(1, round(height)), max(1, round(width))
    angle_radians = radians(normalized)
    corrected_width = ceil(abs(width * cos(angle_radians)) + abs(height * sin(angle_radians)))
    corrected_height = ceil(abs(width * sin(angle_radians)) + abs(height * cos(angle_radians)))
    return max(1, corrected_width), max(1, corrected_height)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


class AnnotationDatabase:
    def __init__(self, path: Path) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS images (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    sha256 TEXT NOT NULL UNIQUE,
                    filename TEXT NOT NULL,
                    source_path TEXT NOT NULL,
                    width INTEGER NOT NULL CHECK (width > 0),
                    height INTEGER NOT NULL CHECK (height > 0),
                    file_size INTEGER NOT NULL CHECK (file_size >= 0),
                    status TEXT NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending', 'annotated', 'reviewed', 'skipped')),
                    split TEXT NOT NULL DEFAULT 'unassigned'
                        CHECK (split IN ('unassigned', 'train', 'validation', 'test')),
                    document_label TEXT NOT NULL DEFAULT '',
                    notes TEXT NOT NULL DEFAULT '',
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    revision INTEGER NOT NULL DEFAULT 0,
                    imported_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    annotated_at TEXT
                );

                CREATE TABLE IF NOT EXISTS regions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    image_id INTEGER NOT NULL REFERENCES images(id) ON DELETE CASCADE,
                    order_index INTEGER NOT NULL,
                    x REAL NOT NULL,
                    y REAL NOT NULL,
                    width REAL NOT NULL CHECK (width > 0),
                    height REAL NOT NULL CHECK (height > 0),
                    baseline_y REAL NOT NULL,
                    baseline_angle REAL NOT NULL DEFAULT 0,
                    line_type TEXT NOT NULL DEFAULT 'DefaultLine',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (image_id, order_index)
                );

                CREATE INDEX IF NOT EXISTS idx_images_status ON images(status, id);
                CREATE INDEX IF NOT EXISTS idx_images_split ON images(split, id);
                CREATE INDEX IF NOT EXISTS idx_regions_image ON regions(image_id, order_index);
                """
            )
            region_columns = {
                str(row["name"])
                for row in connection.execute("PRAGMA table_info(regions)").fetchall()
            }
            if "baseline_angle" not in region_columns:
                connection.execute(
                    "ALTER TABLE regions ADD COLUMN baseline_angle REAL NOT NULL DEFAULT 0"
                )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
        return digest.hexdigest()

    def import_path(self, path: Path) -> tuple[int, bool]:
        source = path.resolve()
        if source.suffix.lower() not in IMAGE_EXTENSIONS or not source.is_file():
            raise ValueError("unsupported_image")
        with Image.open(source) as image:
            oriented = ImageOps.exif_transpose(image)
            width, height = oriented.size
            image_format = image.format or source.suffix.lstrip(".").upper()
        digest = self._sha256(source)
        now = utc_now()
        metadata = json.dumps(
            {"original_format": image_format, "original_path": str(source)},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.connect() as connection:
            existing = connection.execute(
                "SELECT id FROM images WHERE sha256 = ?",
                (digest,),
            ).fetchone()
            if existing is not None:
                return int(existing["id"]), False
            cursor = connection.execute(
                """
                INSERT INTO images (
                    sha256, filename, source_path, width, height, file_size,
                    metadata_json, imported_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    digest,
                    source.name,
                    str(source),
                    width,
                    height,
                    source.stat().st_size,
                    metadata,
                    now,
                    now,
                ),
            )
            return int(cursor.lastrowid), True

    def import_directory(self, directory: Path) -> dict[str, int]:
        imported = 0
        existing = 0
        invalid = 0
        for path in sorted(directory.rglob("*")):
            if not path.is_file() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                _, created = self.import_path(path)
            except (OSError, ValueError):
                invalid += 1
                continue
            if created:
                imported += 1
            else:
                existing += 1
        return {"imported": imported, "existing": existing, "invalid": invalid}

    @staticmethod
    def _row_to_image(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["metadata"] = json.loads(result.pop("metadata_json") or "{}")
        return result

    def list_images(
        self,
        *,
        status: str | None = None,
        search: str | None = None,
        limit: int = 500,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conditions: list[str] = []
        values: list[Any] = []
        if status and status != "all":
            conditions.append("i.status = ?")
            values.append(status)
        if search:
            conditions.append("(i.filename LIKE ? OR i.document_label LIKE ?)")
            needle = f"%{search}%"
            values.extend([needle, needle])
        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        values.extend([limit, offset])
        with self.connect() as connection:
            rows = connection.execute(
                f"""
                SELECT i.*, COUNT(r.id) AS region_count
                FROM images i
                LEFT JOIN regions r ON r.image_id = i.id
                {where}
                GROUP BY i.id
                ORDER BY i.id
                LIMIT ? OFFSET ?
                """,
                values,
            ).fetchall()
        return [self._row_to_image(row) for row in rows]

    def get_image(self, image_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            image = connection.execute(
                """
                SELECT i.*, COUNT(r.id) AS region_count
                FROM images i
                LEFT JOIN regions r ON r.image_id = i.id
                WHERE i.id = ?
                GROUP BY i.id
                """,
                (image_id,),
            ).fetchone()
            if image is None:
                return None
            regions = connection.execute(
                """
                SELECT id, order_index, x, y, width, height, baseline_y, baseline_angle, line_type
                FROM regions
                WHERE image_id = ?
                ORDER BY order_index
                """,
                (image_id,),
            ).fetchall()
        result = self._row_to_image(image)
        result["regions"] = [dict(region) for region in regions]
        return result

    def save_annotations(
        self,
        image_id: int,
        *,
        regions: Sequence[dict[str, Any]],
        split: str,
        document_label: str,
        notes: str,
        metadata: dict[str, Any],
        expected_revision: int | None,
    ) -> dict[str, Any]:
        if split not in {"unassigned", "train", "validation", "test"}:
            raise ValueError("invalid_split")
        now = utc_now()
        with self.connect() as connection:
            image = connection.execute(
                "SELECT width, height, revision FROM images WHERE id = ?",
                (image_id,),
            ).fetchone()
            if image is None:
                raise KeyError(image_id)
            if expected_revision is not None and int(image["revision"]) != expected_revision:
                raise RuntimeError("revision_conflict")
            clean_metadata = dict(metadata)
            orientation, deskew, _ = correction_parameters(clean_metadata)
            clean_metadata["orientation_degrees"] = orientation
            clean_metadata["deskew_degrees"] = round(deskew, 2)
            width, height = corrected_dimensions(
                float(image["width"]),
                float(image["height"]),
                clean_metadata,
            )
            width = float(width)
            height = float(height)
            cleaned: list[dict[str, Any]] = []
            for index, region in enumerate(regions):
                x = max(0.0, min(width, float(region["x"])))
                y = max(0.0, min(height, float(region["y"])))
                region_width = max(1.0, min(width - x, float(region["width"])))
                region_height = max(1.0, min(height - y, float(region["height"])))
                baseline_y = max(y, min(y + region_height, float(region["baseline_y"])))
                baseline_angle = float(region.get("baseline_angle", 0.0))
                if not isfinite(baseline_angle) or not -20.0 <= baseline_angle <= 20.0:
                    raise ValueError("invalid_baseline_angle")
                cleaned.append(
                    {
                        "order_index": index,
                        "x": x,
                        "y": y,
                        "width": region_width,
                        "height": region_height,
                        "baseline_y": baseline_y,
                        "baseline_angle": round(baseline_angle, 2),
                        "line_type": str(region.get("line_type") or "DefaultLine")[:80],
                    }
                )
            connection.execute("DELETE FROM regions WHERE image_id = ?", (image_id,))
            for region in cleaned:
                connection.execute(
                    """
                    INSERT INTO regions (
                        image_id, order_index, x, y, width, height,
                        baseline_y, baseline_angle, line_type, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        image_id,
                        region["order_index"],
                        region["x"],
                        region["y"],
                        region["width"],
                        region["height"],
                        region["baseline_y"],
                        region["baseline_angle"],
                        region["line_type"],
                        now,
                        now,
                    ),
                )
            status = "annotated" if cleaned else "pending"
            connection.execute(
                """
                UPDATE images
                SET status = ?, split = ?, document_label = ?, notes = ?,
                    metadata_json = ?, revision = revision + 1,
                    updated_at = ?, annotated_at = CASE WHEN ? THEN COALESCE(annotated_at, ?) ELSE NULL END
                WHERE id = ?
                """,
                (
                    status,
                    split,
                    document_label[:200],
                    notes[:4000],
                    json.dumps(clean_metadata, ensure_ascii=False, separators=(",", ":")),
                    now,
                    bool(cleaned),
                    now,
                    image_id,
                ),
            )
        saved = self.get_image(image_id)
        if saved is None:
            raise KeyError(image_id)
        return saved

    def stats(self) -> dict[str, int]:
        with self.connect() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN status = 'annotated' THEN 1 ELSE 0 END) AS annotated,
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending,
                    SUM(CASE WHEN status = 'reviewed' THEN 1 ELSE 0 END) AS reviewed
                FROM images
                """
            ).fetchone()
            region_count = connection.execute("SELECT COUNT(*) FROM regions").fetchone()[0]
        return {
            "total": int(row["total"] or 0),
            "annotated": int(row["annotated"] or 0),
            "pending": int(row["pending"] or 0),
            "reviewed": int(row["reviewed"] or 0),
            "regions": int(region_count or 0),
        }

    def export_rows(self) -> list[dict[str, Any]]:
        images = self.list_images(status="all", limit=100_000)
        result: list[dict[str, Any]] = []
        for image in images:
            if int(image["region_count"]) < 1:
                continue
            full = self.get_image(int(image["id"]))
            if full is not None:
                result.append(full)
        return result
