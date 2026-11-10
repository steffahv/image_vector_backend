"""Run a claimed job and commit its database effects with the result."""

import logging
from collections.abc import Mapping
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import set_current_account
from app.documents.service.maintenance_workspaces import find_maintenance_workspace_owner
from app.jobs.models import Job, JobStatus
from app.jobs.schemas import JobContext, JobHandler
from app.jobs.service.queue import MAX_ATTEMPTS, JobClaim, queue_time

logger = logging.getLogger(__name__)


def _record_failure(db: Session, job: Job, code: str) -> None:
    if job.attempts >= MAX_ATTEMPTS:
        job.status = JobStatus.FAILED
    else:
        job.next_run_at = queue_time(db) + timedelta(seconds=30 * 2 ** (job.attempts - 1))
        job.status = JobStatus.PENDING
    job.error_code = code
    job.lease_until = None


def execute_claim(db: Session, claim: JobClaim, handlers: Mapping[str, JobHandler]) -> bool:
    """Ignore stale claims and lock the row until the handler and result finish."""
    # An expired lease can be reclaimed, but the original attempt is still safe if it locks
    # the row before a replacement. This lets a slow batch finish its remaining claims.
    job = db.scalar(
        select(Job)
        .where(
            Job.id == claim.job_id,
            Job.attempts == claim.attempt,
            Job.status == JobStatus.RUNNING,
        )
        .with_for_update(skip_locked=True)
    )
    if job is None:
        return False

    owner = (
        None if job.workspace_id is None else find_maintenance_workspace_owner(db, job.workspace_id)
    )
    if job.workspace_id is not None and owner is None:
        _record_failure(db, job, "workspace_unavailable")
        db.flush()
        return False
    set_current_account(db, owner)

    try:
        # Even if the handler commits its session, its writes stay inside the worker savepoint.
        with db.begin_nested():
            with Session(
                bind=db.connection(),
                join_transaction_mode="create_savepoint",
                autoflush=db.autoflush,
                expire_on_commit=False,
            ) as handler_db:
                set_current_account(handler_db, owner)
                handlers[job.type](handler_db, JobContext(job.id, job.workspace_id, job.payload))
                handler_db.commit()
    except Exception as error:
        logger.error(
            "Job %s (%s), attempt %s failed with %s",
            job.id,
            job.type,
            job.attempts,
            type(error).__name__,
        )
        _record_failure(db, job, "handler_failed")
    else:
        job.status = JobStatus.COMPLETED
        job.error_code = None
        job.lease_until = None
    finally:
        set_current_account(db, None)

    db.flush()
    return True
