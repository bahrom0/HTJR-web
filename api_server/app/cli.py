from __future__ import annotations

import uvicorn
import argparse

from app.core.settings import settings
from app.worker.main import run as run_worker_process
from app.core.database import Database
from app.services.access import AccessService


def run_api() -> None:
    uvicorn.run("app.main:app", host=settings.host, port=settings.port)


def run_worker() -> None:
    run_worker_process()


def issue_access_code() -> None:
    parser = argparse.ArgumentParser(description="Issue a one-time Tajik HTR Studio access code")
    parser.add_argument("--label")
    args = parser.parse_args()
    database = Database(settings.database_path)
    database.migrate()
    code, expires_at = AccessService(database, settings).issue_code(args.label)
    print(f"Access code (shown once): {code}")
    print(f"Expires at: {expires_at}")
