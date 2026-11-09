import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum


class ByteReservationStatus(StrEnum):
    """Lifecycle of a byte reservation (Modelo relacional §X: reserved, consumed, released)."""

    RESERVED = "reserved"
    CONSUMED = "consumed"
    RELEASED = "released"


class ByteReservation(UUIDPrimaryKey, CreatedAt, Base):
    """Space held for one upload until it is confirmed (consumed) or fails (released).

    Holding the space first stops two uploads at once from passing the workspace limit.
    """

    __tablename__ = "byte_reservations"
    __table_args__ = (
        UniqueConstraint("upload_id"),
        ForeignKeyConstraint(
            ["workspace_id", "upload_id"],
            ["storage.uploads.workspace_id", "storage.uploads.id"],
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        # Cleanup job: release reservations whose upload never finished.
        Index(None, "status", "expires_at"),
        {"schema": DbSchema.STORAGE},
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("storage.workspace_quotas.workspace_id"), index=True
    )
    upload_id: Mapped[uuid.UUID]
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[ByteReservationStatus] = mapped_column(
        text_enum(ByteReservationStatus, "status")
    )
    expires_at: Mapped[datetime]
