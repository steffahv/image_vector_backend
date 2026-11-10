import uuid
from datetime import datetime
from enum import StrEnum

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, ForeignKey, Index, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum

RETIRED_SCHEDULED_JOB = (
    "status IN ('completed', 'failed', 'cancelled')"
    " AND split_part(idempotency_key, ':', 2) = 'scheduled'"
    " AND type <> 'generate_export'"
)


class JobStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class Job(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "jobs"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        CheckConstraint("attempts >= 0", name="attempts_non_negative"),
        CheckConstraint("(status = 'running') = (lease_until IS NOT NULL)", name="running_lease"),
        CheckConstraint("jsonb_typeof(payload) = 'object'", name="payload_object"),
        Index(None, "status", "next_run_at"),
        Index(None, "status", "lease_until"),
        Index(
            "ix_jobs_retention", "updated_at", "id", postgresql_where=text(RETIRED_SCHEDULED_JOB)
        ),
        {"schema": DbSchema.OPERATIONS},
    )

    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform.workspaces.id", ondelete="CASCADE")
    )
    type: Mapped[str]
    idempotency_key: Mapped[str] = mapped_column(unique=True)
    payload: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)
    status: Mapped[JobStatus] = mapped_column(
        text_enum(JobStatus, "status"), server_default=JobStatus.PENDING.value
    )
    attempts: Mapped[int] = mapped_column(server_default=text("0"))
    next_run_at: Mapped[datetime] = mapped_column(server_default=func.now())
    lease_until: Mapped[datetime | None]
    error_code: Mapped[str | None]
