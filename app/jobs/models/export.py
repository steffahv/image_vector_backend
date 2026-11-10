import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class ExportStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Export(UUIDPrimaryKey, Timestamps, Base):
    """An export request and the final object produced by its job."""

    __tablename__ = "exports"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "job_id"], ["operations.jobs.workspace_id", "operations.jobs.id"]
        ),
        ForeignKeyConstraint(
            ["workspace_id", "object_id"], ["storage.objects.workspace_id", "storage.objects.id"]
        ),
        CheckConstraint("status <> 'completed' OR object_id IS NOT NULL", name="completed_object"),
        CheckConstraint("status <> 'expired' OR object_id IS NULL", name="expired_object"),
        Index(None, "account_id"),
        Index(None, "workspace_id", "object_id"),
        Index(None, "status", "expires_at"),
        {"schema": DbSchema.OPERATIONS},
    )

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform.workspaces.id", ondelete="CASCADE")
    )
    job_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    object_id: Mapped[uuid.UUID | None]
    status: Mapped[ExportStatus] = mapped_column(
        text_enum(ExportStatus, "status"), server_default=ExportStatus.PENDING.value
    )
    expires_at: Mapped[datetime]
