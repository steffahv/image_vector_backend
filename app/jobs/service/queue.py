"""Queue writes participate in the caller's transaction."""

import uuid
from collections.abc import Collection
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.jobs.models import Job, JobStatus
from app.jobs.schemas.job_request import JobRequest

MAX_ATTEMPTS = 5
LEASE = timedelta(minutes=5)
BATCH_SIZE = 10


@dataclass(frozen=True)
class JobClaim:
    job_id: uuid.UUID
    attempt: int


def enqueue_job(db: Session, request: JobRequest) -> uuid.UUID:
    """Return the job ID, including when the same request was already enqueued."""
    scope = request.workspace_id or "global"
    key = f"{scope}:{request.idempotency_key}"
    statement = (
        insert(Job)
        .values(
            workspace_id=request.workspace_id,
            type=request.type,
            idempotency_key=key,
            payload=request.payload,
            next_run_at=request.next_run_at or func.now(),
        )
        .on_conflict_do_nothing(index_elements=[Job.idempotency_key])
        .returning(Job.id)
    )
    job_id: uuid.UUID | None = db.scalar(statement)
    if job_id is not None:
        return job_id

    # PostgreSQL compares JSONB values without Python's equivalence between True and 1.
    existing_id = db.scalar(
        select(Job.id).where(
            Job.idempotency_key == key,
            Job.workspace_id == request.workspace_id,
            Job.type == request.type,
            Job.payload == request.payload,
        )
    )
    if existing_id is None:
        raise ValueError("job idempotency key is unavailable for this request")
    return existing_id


def queue_time(db: Session) -> datetime:
    now: datetime = db.execute(select(func.clock_timestamp())).scalar_one()
    return now


def claim_jobs(db: Session, job_types: Collection[str]) -> list[JobClaim]:
    """Lease a batch without waiting for rows held by another worker."""
    if not job_types:
        return []
    now = queue_time(db)
    eligible = or_(
        and_(Job.status == JobStatus.PENDING, Job.next_run_at <= now),
        and_(Job.status == JobStatus.RUNNING, Job.lease_until <= now),
    )
    rows = db.scalars(
        select(Job)
        .where(Job.type.in_(job_types), eligible)
        .order_by(Job.next_run_at, Job.id)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    )
    claims = []
    for job in rows:
        if job.attempts >= MAX_ATTEMPTS:
            job.status = JobStatus.FAILED
            job.lease_until = None
            job.error_code = "lease_exhausted"
            continue
        job.attempts += 1
        job.status = JobStatus.RUNNING
        job.lease_until = now + LEASE
        claims.append(JobClaim(job.id, job.attempts))
    db.flush()
    return claims
