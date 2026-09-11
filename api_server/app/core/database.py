from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from types import TracebackType
from typing import Iterator


class _ClosingConnection(sqlite3.Connection):
    """Close read-scoped SQLite handles when a ``with`` block exits.

    ``sqlite3.Connection.__exit__`` commits or rolls back but deliberately
    leaves the native handle open.  Repository reads consistently use
    ``with database.connect()``, so preserving the standard behavior leaks
    file handles until garbage collection and blocks temporary DB cleanup on
    Windows.  The database boundary owns that lifecycle instead.
    """

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        try:
            return super().__exit__(exception_type, exception, traceback)
        finally:
            self.close()


class Database:
    def __init__(self, path: Path, migrations_dir: Path | None = None) -> None:
        self.path = path
        self.migrations_dir = migrations_dir or Path(__file__).resolve().parents[2] / "migrations"

    def connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(
            self.path,
            timeout=5,
            isolation_level=None,
            factory=_ClosingConnection,
        )
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def migrate(self) -> None:
        from app.core.settings import settings
        if settings.supabase_url and settings.supabase_key:
            import logging
            logging.getLogger(__name__).info("Supabase PostgreSQL active. Local SQLite migrations skipped.")
            return

        connection = self.connect()
        try:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_migrations (version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
            )
            applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
            migrations = sorted(self.migrations_dir.glob("[0-9]*_*.sql"))
            pending = [migration for migration in migrations if migration.name not in applied]
            if applied and pending:
                backup_path = self.path.with_name(
                    f"{self.path.name}.backup-before-{pending[0].stem}"
                )
                if not backup_path.exists():
                    backup = sqlite3.connect(backup_path)
                    try:
                        connection.backup(backup)
                    finally:
                        backup.close()
            for migration in migrations:
                if migration.name in applied:
                    continue
                version = migration.name.replace("'", "''")
                migration_sql = migration.read_text(encoding="utf-8")
                foreign_keys_off = migration_sql.lstrip().startswith("-- migrate: foreign_keys_off")
                if foreign_keys_off:
                    connection.execute("PRAGMA foreign_keys = OFF")
                try:
                    connection.executescript(
                        f"BEGIN IMMEDIATE;\n{migration_sql}\n"
                        f"INSERT INTO schema_migrations(version) VALUES ('{version}');\nCOMMIT;"
                    )
                    if foreign_keys_off:
                        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
                        if violations:
                            raise sqlite3.IntegrityError(
                                f"Foreign key violations after migration {migration.name}: {len(violations)}"
                            )
                finally:
                    if foreign_keys_off:
                        connection.execute("PRAGMA foreign_keys = ON")
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def close(self) -> None:
        # Connections are deliberately short-lived and transaction-scoped.
        return None
