from __future__ import annotations

import hashlib
import os
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO
from collections.abc import AsyncIterator


@dataclass(frozen=True, slots=True)
class StoredFile:
    storage_key: str
    sha256: str
    byte_size: int
    path: Path


class FileStorage:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.temporary = self.root / ".temporary"
        self.committed = self.root / "committed"
        self.temporary.mkdir(parents=True, exist_ok=True)
        self.committed.mkdir(parents=True, exist_ok=True)

    def resolve(self, storage_key: str, *, temporary: bool = False) -> Path:
        if not storage_key or Path(storage_key).is_absolute():
            raise ValueError("Invalid storage key")
        base = self.temporary if temporary else self.committed
        candidate = (base / storage_key).resolve()
        if not candidate.is_relative_to(base.resolve()):
            raise ValueError("Storage key escapes the configured root")
        return candidate

    def stage(self, source: BinaryIO) -> StoredFile:
        key = f"{secrets.token_hex(2)}/{secrets.token_hex(16)}"
        destination = self.resolve(key, temporary=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        with destination.open("xb") as target:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                target.write(chunk)
            target.flush()
            os.fsync(target.fileno())
        return StoredFile(key, digest.hexdigest(), size, destination)

    async def stage_stream(self, chunks: AsyncIterator[bytes], *, max_bytes: int) -> StoredFile:
        key = f"{secrets.token_hex(2)}/{secrets.token_hex(16)}"
        destination = self.resolve(key, temporary=True)
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        size = 0
        try:
            with destination.open("xb") as target:
                async for chunk in chunks:
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise OverflowError("Upload byte limit exceeded")
                    digest.update(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
        return StoredFile(key, digest.hexdigest(), size, destination)

    def commit(self, staged: StoredFile) -> StoredFile:
        source = self.resolve(staged.storage_key, temporary=True)
        destination = self.resolve(staged.storage_key)
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.replace(destination)
        return StoredFile(staged.storage_key, staged.sha256, staged.byte_size, destination)

    def discard_temporary(self, storage_key: str) -> None:
        path = self.resolve(storage_key, temporary=True)
        path.unlink(missing_ok=True)

    def discard_committed(self, storage_key: str) -> None:
        self.resolve(storage_key).unlink(missing_ok=True)

    def purge_temporary(self, *, older_than_seconds: int) -> int:
        if older_than_seconds < 0:
            raise ValueError("Retention duration cannot be negative")
        cutoff = time.time() - older_than_seconds
        removed = 0
        for path in self.temporary.rglob("*"):
            if path.is_file() and path.stat().st_mtime < cutoff:
                path.unlink()
                removed += 1
        return removed
