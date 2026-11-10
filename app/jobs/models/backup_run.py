from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, UUIDPrimaryKey, text_enum


class BackupType(StrEnum):
    """What a backup run copies."""

    DATABASE = "database"
    OBJECTS = "objects"


class BackupStatus(StrEnum):
    """Lifecycle of a backup run."""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class BackupRun(UUIDPrimaryKey, Base):
    """One global backup run. Global: no account data and no foreign key to the copied rows.

    The files it covers are listed in its manifest, not linked to object_copies (§VIII).
    """

    __tablename__ = "backup_runs"
    __table_args__ = (
        CheckConstraint("finished_at >= started_at", name="finishes_after_start"),
        {"schema": DbSchema.OPERATIONS},
    )

    type: Mapped[BackupType] = mapped_column(text_enum(BackupType, "type"))
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    status: Mapped[BackupStatus] = mapped_column(text_enum(BackupStatus, "status"))
    manifest: Mapped[str | None]
    recovery_point_at: Mapped[datetime | None]
    verification_result: Mapped[str | None]
