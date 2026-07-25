from __future__ import annotations

import json
from datetime import UTC, datetime
from uuid import uuid4

from app.core.database import Database


class PageNotFound(Exception):
    pass


class RegionRevisionConflict(Exception):
    pass


def _now() -> str:
    return datetime.now(UTC).isoformat()


class RegionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list(self, owner_session_id: str, page_id: str) -> tuple[int, int | None, list[dict[str, object]]]:
        with self.database.connect() as connection:
            page = connection.execute(
                """SELECT p.revision,p.regions_confirmed_revision FROM pages p
                   JOIN documents d ON d.id=p.document_id
                   WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
                (page_id, owner_session_id),
            ).fetchone()
            if page is None:
                raise PageNotFound(page_id)
            rows = connection.execute(
                """SELECT id,polygon_json,reading_order,revision,source,flags_json,detector_version,detector_score
                   FROM recognition_regions WHERE page_id=? ORDER BY reading_order,id""",
                (page_id,),
            ).fetchall()
        return (
            page["revision"],
            page["regions_confirmed_revision"],
            [
                {
                    "id": row["id"],
                    "polygon": json.loads(row["polygon_json"]),
                    "reading_order": row["reading_order"],
                    "revision": row["revision"],
                    "source": row["source"],
                    "flags": json.loads(row["flags_json"]),
                    "detector_version": row["detector_version"],
                    "detector_score": row["detector_score"],
                }
                for row in rows
            ],
        )

    def replace(self, owner_session_id: str, page_id: str, expected_revision: int, regions: list[dict[str, object]]) -> int:
        now = _now()
        with self.database.transaction(immediate=True) as connection:
            page = connection.execute(
                """SELECT p.revision FROM pages p JOIN documents d ON d.id=p.document_id
                   WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
                (page_id, owner_session_id),
            ).fetchone()
            if page is None:
                raise PageNotFound(page_id)
            if page["revision"] != expected_revision:
                raise RegionRevisionConflict(page_id)
            connection.execute("DELETE FROM recognition_regions WHERE page_id=?", (page_id,))
            for region in regions:
                connection.execute(
                    """INSERT INTO recognition_regions(
                           id,page_id,polygon_json,reading_order,revision,created_at,updated_at,
                           source,flags_json,detector_version,detector_score)
                       VALUES (?,?,?,?,1,?,?,?,?,?,?)""",
                    (
                        region.get("id") or str(uuid4()),
                        page_id,
                        json.dumps(region["polygon"], separators=(",", ":")),
                        region["reading_order"],
                        now,
                        now,
                        region["source"],
                        json.dumps(region["flags"], separators=(",", ":")),
                        region.get("detector_version"),
                        region.get("detector_score"),
                    ),
                )
            connection.execute(
                """UPDATE pages SET revision=revision+1,regions_confirmed_revision=NULL,
                   regions_confirmed_at=NULL,updated_at=? WHERE id=?""",
                (now, page_id),
            )
        return expected_revision + 1

    def confirm(self, owner_session_id: str, page_id: str, expected_revision: int) -> int:
        now = _now()
        with self.database.transaction(immediate=True) as connection:
            page = connection.execute(
                """SELECT p.revision FROM pages p JOIN documents d ON d.id=p.document_id
                   WHERE p.id=? AND d.owner_session_id=? AND d.deleted_at IS NULL""",
                (page_id, owner_session_id),
            ).fetchone()
            if page is None:
                raise PageNotFound(page_id)
            if page["revision"] != expected_revision:
                raise RegionRevisionConflict(page_id)
            connection.execute(
                """UPDATE pages SET regions_confirmed_revision=?,regions_confirmed_at=?,
                   revision=revision+1,updated_at=? WHERE id=?""",
                (expected_revision + 1, now, now, page_id),
            )
        return expected_revision + 1
