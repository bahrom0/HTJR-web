"""Serving helpers for the compiled local web client."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException
from starlette.responses import FileResponse, Response
from starlette.types import Scope


class SpaStaticFiles(StaticFiles):
    """Static files with a safe HTML fallback for client-side routes."""

    async def get_response(self, path: str, scope: Scope) -> Response:
        relative_path = scope["path"].lstrip("/")
        is_client_route = (
            scope["method"] in {"GET", "HEAD"}
            and "." not in Path(relative_path).name
            and not relative_path.startswith(("api/", "events/"))
        )
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            if error.status_code != 404 or not is_client_route:
                raise
            return FileResponse(Path(self.directory) / "index.html")
        if response.status_code != 404 or not is_client_route:
            return response
        return FileResponse(Path(self.directory) / "index.html")


def mount_web_client(application: FastAPI, web_dist: Path) -> None:
    """Mount a verified Vite build after all API routes are registered."""
    index_path = web_dist / "index.html"
    if not index_path.is_file():
        raise ValueError(f"Compiled web client is missing index.html: {web_dist}")
    mimetypes.add_type("application/javascript", ".js", strict=True)
    mimetypes.add_type("text/css", ".css", strict=True)
    application.mount("/", SpaStaticFiles(directory=web_dist, html=True), name="web-client")
