"""Expiration and generation guards for export records."""

from pydantic import AwareDatetime, TypeAdapter
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.jobs.models import Export, ExportStatus
from app.jobs.schemas import JobContext, JobHandler

DATETIME = TypeAdapter(AwareDatetime)


def expire_exports(db: Session, job: JobContext) -> None:
    """Release expired exports' file references, without deleting stored objects."""
    if job.workspace_id is None:
        raise ValueError("export expiration requires a workspace")
    cutoff = DATETIME.validate_python(job.payload["as_of"])
    due = (
        select(Export.id)
        .where(
            Export.workspace_id == job.workspace_id,
            Export.expires_at <= cutoff,
            Export.status != ExportStatus.EXPIRED,
        )
        .with_for_update(skip_locked=True)
    )
    db.execute(
        update(Export).where(Export.id.in_(due)).values(status=ExportStatus.EXPIRED, object_id=None)
    )


def generate_if_current(db: Session, job: JobContext, generate: JobHandler) -> None:
    """Hold the export row through generation so expiration and generation cannot race."""
    export_id = db.scalar(
        select(Export.id)
        .where(
            Export.job_id == job.id,
            Export.workspace_id == job.workspace_id,
            Export.status.in_((ExportStatus.PENDING, ExportStatus.RUNNING)),
            Export.expires_at > func.clock_timestamp(),
        )
        .with_for_update()
    )
    if export_id is not None:
        generate(db, job)
