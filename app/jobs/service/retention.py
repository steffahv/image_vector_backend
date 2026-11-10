"""Remove old scheduler rows without touching jobs used by exports."""

from datetime import timedelta

from sqlalchemy import delete, select, text
from sqlalchemy.orm import Session

from app.jobs.models import Job
from app.jobs.models.job import RETIRED_SCHEDULED_JOB
from app.jobs.service.queue import queue_time

RETENTION = timedelta(days=30)
PURGE_BATCH_SIZE = 1000


def purge_retired_jobs(db: Session) -> None:
    old_ids = (
        select(Job.id)
        .where(text(RETIRED_SCHEDULED_JOB), Job.updated_at < queue_time(db) - RETENTION)
        .order_by(Job.updated_at, Job.id)
        .limit(PURGE_BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    db.execute(delete(Job).where(Job.id.in_(old_ids)))
