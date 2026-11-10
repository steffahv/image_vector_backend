"""Schedule bounded maintenance work for each workspace with an installed handler."""

from collections.abc import Collection
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.documents.service.maintenance_workspaces import list_maintenance_workspaces
from app.jobs.schemas.job_request import JobRequest
from app.jobs.service.queue import enqueue_job, queue_time


@dataclass(frozen=True)
class MaintenanceSchedule:
    type: str
    interval: timedelta
    retention: timedelta | None = None


SCHEDULES = (
    MaintenanceSchedule("expire_uploads_and_reservations", timedelta(minutes=5)),
    MaintenanceSchedule("expire_exports", timedelta(hours=1)),
    MaintenanceSchedule("purge_trash", timedelta(days=1), timedelta(days=30)),
    MaintenanceSchedule("prune_versions", timedelta(days=1)),
    MaintenanceSchedule("delete_unused_objects", timedelta(days=1), timedelta(days=8)),
    MaintenanceSchedule("reconcile_storage_quotas", timedelta(days=1)),
)


def enqueue_maintenance(db: Session, job_types: Collection[str]) -> None:
    enabled = [schedule for schedule in SCHEDULES if schedule.type in job_types]
    if not enabled:
        return
    now = queue_time(db)
    workspaces = list_maintenance_workspaces(db)
    for schedule in enabled:
        seconds = int(schedule.interval.total_seconds())
        slot = datetime.fromtimestamp(int(now.timestamp()) // seconds * seconds, UTC)
        payload = {"as_of": slot.isoformat()}
        if schedule.retention is not None:
            payload["older_than"] = (slot - schedule.retention).isoformat()
        for workspace_id in workspaces:
            enqueue_job(
                db,
                JobRequest(
                    type=schedule.type,
                    workspace_id=workspace_id,
                    idempotency_key=f"scheduled:{schedule.type}:{slot.isoformat()}",
                    payload=payload,
                    next_run_at=slot,
                ),
            )
