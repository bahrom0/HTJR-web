from __future__ import annotations

import logging
import signal
import threading
from uuid import uuid4

from app.core.database import Database
from app.core.logging import configure_logging
from app.core.settings import settings
from app.repositories.jobs import JobRepository
from app.services.jobs import WorkerService


def run() -> None:
    configure_logging()
    database = Database(settings.database_path)
    database.migrate()
    stop_event = threading.Event()
    worker_id = f"worker-{uuid4()}"
    service = WorkerService(
        JobRepository(database), worker_id=worker_id, lease_seconds=settings.worker_lease_seconds,
        heartbeat_seconds=settings.worker_heartbeat_seconds, handlers={}
    )

    def stop(_signum, _frame) -> None:
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    logging.getLogger(__name__).info("worker_started worker_id=%s mode=no_ml_pipeline_registered", worker_id)
    service.run_forever(stop_event, poll_seconds=settings.worker_poll_seconds)


if __name__ == "__main__":
    run()
