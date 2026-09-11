from __future__ import annotations

import io
import json
import logging
import urllib.error
import urllib.request
from pathlib import Path

logger = logging.getLogger(__name__)


class SupabaseStorage:
    def __init__(self, url: str | None, key: str | None, bucket: str = "htr-uploads", local_fallback_dir: Path | None = None) -> None:
        self.url = (url or "").rstrip("/")
        self.key = key or ""
        self.bucket = bucket
        self.local_fallback_dir = local_fallback_dir or Path(__file__).resolve().parents[2] / "data" / "assets"
        self.local_fallback_dir.mkdir(parents=True, exist_ok=True)
        self._memory_cache: dict[str, bytes] = {}

    def resolve(self, storage_key: str, *, temporary: bool = False) -> Path:
        # Save to local file if not present on disk
        local_path = self.local_fallback_dir / storage_key.replace("/", "_")
        if not local_path.is_file() and storage_key in self._memory_cache:
            local_path.write_bytes(self._memory_cache[storage_key])
        elif not local_path.is_file() and self.is_configured:
            try:
                data = self.download(storage_key)
                local_path.write_bytes(data)
            except Exception:
                pass
        return local_path

    @property
    def is_configured(self) -> bool:
        return bool(self.url and self.key)

    def get_public_url(self, storage_key: str) -> str:
        if self.is_configured:
            return f"{self.url}/storage/v1/object/public/{self.bucket}/{storage_key}"
        return f"/api/v1/assets/{storage_key}"

    def upload(self, storage_key: str, data: bytes, content_type: str = "image/png") -> str:
        # Always store in memory / local fallback first
        self._memory_cache[storage_key] = data
        try:
            local_path = self.local_fallback_dir / storage_key.replace("/", "_")
            local_path.write_bytes(data)
        except Exception as e:
            logger.debug("Local disk fallback write skipped: %s", e)

        if not self.is_configured:
            return self.get_public_url(storage_key)

        endpoint = f"{self.url}/storage/v1/object/{self.bucket}/{storage_key}"
        headers = {
            "apikey": self.key,
            "Authorization": f"Bearer {self.key}",
            "Content-Type": content_type,
            "x-upsert": "true",
        }
        req = urllib.request.Request(endpoint, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                logger.info("Uploaded %s to Supabase Storage: status %s", storage_key, resp.status)
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode(errors="ignore")
            logger.warning("Supabase Storage upload returned %s: %s (using local fallback cache)", exc.code, err_body)
        except Exception as exc:
            logger.warning("Supabase Storage upload failed: %s (using local fallback cache)", exc)

        return self.get_public_url(storage_key)

    def download(self, storage_key: str) -> bytes:
        # Check memory cache first
        if storage_key in self._memory_cache:
            return self._memory_cache[storage_key]

        # Check local disk
        local_path = self.local_fallback_dir / storage_key.replace("/", "_")
        if local_path.is_file():
            return local_path.read_bytes()

        # Try Supabase download
        if self.is_configured:
            endpoint = f"{self.url}/storage/v1/object/{self.bucket}/{storage_key}"
            headers = {
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
            }
            req = urllib.request.Request(endpoint, headers=headers)
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = resp.read()
                    self._memory_cache[storage_key] = data
                    return data
            except Exception as exc:
                logger.warning("Could not download %s from Supabase: %s", storage_key, exc)

        raise FileNotFoundError(f"Asset not found: {storage_key}")
