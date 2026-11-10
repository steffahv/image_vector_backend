"""Run the jobs process with its own DATABASE_URL and the platform's service modules."""

import logging
import signal
from collections.abc import Mapping
from threading import Event
from time import monotonic
from types import FrameType

from sqlalchemy.orm import Session, sessionmaker

from app.core.db import SessionLocal, check_app_role, engine
from app.jobs.schemas import JobHandler
from app.jobs.service.execution import execute_claim
from app.jobs.service.handlers import installed_handlers
from app.jobs.service.queue import claim_jobs
from app.jobs.service.retention import purge_retired_jobs
from app.jobs.service.schedule import enqueue_maintenance


def run_cycle(
    sessions: sessionmaker[Session],
    handlers: Mapping[str, JobHandler],
    *,
    schedule: bool = False,
    stopping: Event | None = None,
) -> int:
    if schedule:
        with sessions.begin() as db:
            purge_retired_jobs(db)
        with sessions.begin() as db:
            enqueue_maintenance(db, handlers.keys())
    with sessions.begin() as db:
        claims = claim_jobs(db, handlers.keys())

    processed = 0
    for claim in claims:
        if stopping is not None and stopping.is_set():
            break
        with sessions.begin() as db:
            processed += execute_claim(db, claim, handlers)
    return processed


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    with engine.connect() as connection:
        check_app_role(connection, worker=True)
    handlers = installed_handlers()

    stopping = Event()

    def stop(_signal: int, _frame: FrameType | None) -> None:
        stopping.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)

    next_schedule = 0.0
    while not stopping.is_set():
        now = monotonic()
        schedule = now >= next_schedule
        if schedule:
            next_schedule = now + 60
        if run_cycle(SessionLocal, handlers, schedule=schedule, stopping=stopping) == 0:
            stopping.wait(1)


if __name__ == "__main__":
    main()
