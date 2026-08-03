from __future__ import annotations

import uvicorn

from app.core.settings import settings
from app.worker.main import run as run_worker_process


def run_api() -> None:
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)


def run_worker() -> None:
    run_worker_process()
