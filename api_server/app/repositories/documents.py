from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from uuid import uuid4

from app.core.database import Database


class RevisionConflict(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Document:
    id: str
    owner_session_id: str
    title: str
    status: str
    revision: int
    deleted_at: str | None


_TRANSITIONS = {"draft": {"ready"}, "ready": {"processing", "draft"}, "processing": {"review", "failed"}, "failed": {"processing"}, "review": {"confirmed"}, "confirmed": set()}


class DocumentRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def create(self, owner_session_id: str, title: str) -> Document:
        now = datetime.now(UTC).isoformat()
        document_id = str(uuid4())
        with self.database.transaction(immediate=True) as connection:
            connection.execute(
                "INSERT INTO documents(id, owner_session_id, title, created_at, updated_at) VALUES (?,?,?,?,?)",
                (document_id, owner_session_id, title, now, now),
            )
        return self.get(owner_session_id, document_id)

    def get(self, owner_session_id: str, document_id: str) -> Document:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT id, owner_session_id, title, status, revision, deleted_at FROM documents WHERE id=? AND owner_session_id=? AND deleted_at IS NULL",
                (document_id, owner_session_id),
            ).fetchone()
        if row is None:
            raise KeyError(document_id)
        return Document(**dict(row))

    def update(self, owner_session_id: str, document_id: str, expected_revision: int, *, title: str | None = None, status: str | None = None) -> Document:
        now = datetime.now(UTC).isoformat()
        current = self.get(owner_session_id, document_id)
        if status is not None and status != current.status and status not in _TRANSITIONS.get(current.status, set()):
            raise ValueError(f"Invalid document transition: {current.status} -> {status}")
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE documents SET title=?, status=?, revision=revision+1, updated_at=? WHERE id=? AND owner_session_id=? AND revision=? AND deleted_at IS NULL",
                (title or current.title, status or current.status, now, document_id, owner_session_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RevisionConflict(document_id)
        return self.get(owner_session_id, document_id)

    def soft_delete(self, owner_session_id: str, document_id: str, expected_revision: int) -> None:
        now = datetime.now(UTC).isoformat()
        with self.database.transaction(immediate=True) as connection:
            cursor = connection.execute(
                "UPDATE documents SET deleted_at=?, updated_at=?, revision=revision+1 WHERE id=? AND owner_session_id=? AND revision=? AND deleted_at IS NULL",
                (now, now, document_id, owner_session_id, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RevisionConflict(document_id)

    def create_asset(self, owner_session_id: str, storage_key: str, sha256: str, byte_size: int, media_type: str, document_id: str | None = None) -> str:
        if document_id is not None:
            self.get(owner_session_id, document_id)
        asset_id = str(uuid4())
        now = datetime.now(UTC).isoformat()
        try:
            with self.database.transaction(immediate=True) as connection:
                connection.execute(
                    "INSERT INTO assets(id, owner_session_id, document_id, storage_key, sha256, byte_size, media_type, state, created_at, committed_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (asset_id, owner_session_id, document_id, storage_key, sha256, byte_size, media_type, "committed", now, now),
                )
        except sqlite3.IntegrityError as error:
            raise ValueError("Asset metadata is invalid or orphaned") from error
        return asset_id
