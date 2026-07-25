from __future__ import annotations

import sqlite3

import pytest

from app.core.database import Database


def test_connection_context_closes_native_handle_after_read_scope(tmp_path) -> None:
    database = Database(tmp_path / "studio.sqlite3")
    database.migrate()

    connection = database.connect()
    with connection as active:
        assert active.execute("SELECT 1").fetchone()[0] == 1

    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
