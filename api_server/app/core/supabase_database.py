from __future__ import annotations

import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterator
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class SupabaseConnectionError(RuntimeError):
    pass


class SupabaseQueryBuilder:
    def __init__(self, base_url: str, key: str, table: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.key = key
        self.table = table
        self._headers = {
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _url(self, query: str = "") -> str:
        return f"{self.base_url}/rest/v1/{self.table}{('?' + query) if query else ''}"

    def select(self, columns: str = "*", filters: dict[str, str] | None = None, order: str | None = None) -> list[dict[str, Any]]:
        params: list[str] = [f"select={urllib.parse.quote(columns)}"]
        if filters:
            for k, v in filters.items():
                params.append(f"{k}=eq.{urllib.parse.quote(str(v))}")
        if order:
            params.append(f"order={urllib.parse.quote(order)}")
        
        req = urllib.request.Request(self._url("&".join(params)), headers=self._headers, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, list) else [data]
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            logger.error("Supabase select failed on %s: status %s, %s", self.table, exc.code, err_body)
            raise SupabaseConnectionError(f"Supabase select failed: {err_body}") from exc

    def insert(self, record: dict[str, Any] | list[dict[str, Any]], upsert: bool = False) -> list[dict[str, Any]]:
        headers = dict(self._headers)
        headers["Prefer"] = "return=representation"
        if upsert:
            headers["Prefer"] += ",resolution=merge-duplicates"

        body = json.dumps(record).encode("utf-8")
        req = urllib.request.Request(self._url(), data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, list) else [data]
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            logger.error("Supabase insert failed on %s: status %s, %s", self.table, exc.code, err_body)
            raise SupabaseConnectionError(f"Supabase insert failed: {err_body}") from exc

    def update(self, record: dict[str, Any], filters: dict[str, str]) -> list[dict[str, Any]]:
        headers = dict(self._headers)
        headers["Prefer"] = "return=representation"
        params = [f"{k}=eq.{urllib.parse.quote(str(v))}" for k, v in filters.items()]
        body = json.dumps(record).encode("utf-8")
        req = urllib.request.Request(self._url("&".join(params)), data=body, headers=headers, method="PATCH")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return data if isinstance(data, list) else [data]
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            logger.error("Supabase update failed on %s: status %s, %s", self.table, exc.code, err_body)
            raise SupabaseConnectionError(f"Supabase update failed: {err_body}") from exc

    def delete(self, filters: dict[str, str]) -> None:
        params = [f"{k}=eq.{urllib.parse.quote(str(v))}" for k, v in filters.items()]
        req = urllib.request.Request(self._url("&".join(params)), headers=self._headers, method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                pass
        except urllib.error.HTTPError as exc:
            err_body = exc.read().decode("utf-8", errors="ignore")
            logger.error("Supabase delete failed on %s: status %s, %s", self.table, exc.code, err_body)
            raise SupabaseConnectionError(f"Supabase delete failed: {err_body}") from exc


class SupabaseDatabase:
    """Cloud database client connecting exclusively to Supabase PostgREST.
    
    Local SQLite is completely disabled. All queries and mutations route
    to the managed Supabase PostgreSQL schema.
    """
    def __init__(self, url: str | None, key: str | None) -> None:
        if not url or not key:
            raise SupabaseConnectionError("SUPABASE_URL and SUPABASE_KEY are required. Local SQLite is disabled.")
        self.url = url.rstrip("/")
        self.key = key
        logger.info("Initialized SupabaseDatabase connected to %s (local SQLite disabled)", self.url)

    def table(self, table_name: str) -> SupabaseQueryBuilder:
        return SupabaseQueryBuilder(self.url, self.key, table_name)

    @contextmanager
    def connect(self) -> Iterator[SupabaseDatabase]:
        yield self

    @contextmanager
    def transaction(self, *, immediate: bool = False) -> Iterator[SupabaseDatabase]:
        yield self

    def migrate(self) -> None:
        # Schema migrations on Supabase are managed via Supabase SQL Editor
        # using the provided supabase_schema.sql DDL script.
        logger.info("Supabase database active. Local SQLite migration skipped.")

    def close(self) -> None:
        pass
