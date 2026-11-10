import uuid
from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class PendingCallStatus(StrEnum):
    """Lifecycle of a tool call sent to the editor tab."""

    PENDING = "pending"
    COMPLETED = "completed"
    FAILED = "failed"
    EXPIRED = "expired"


class PendingCall(UUIDPrimaryKey, Timestamps, Base):
    """A tool call the agent asked the editor to run, until its result comes back.

    A dropped connection must not repeat a write: the run checks this row before retrying.
    """

    __tablename__ = "pending_calls"
    __table_args__ = (
        UniqueConstraint("run_id", "call_id"),
        # Expiry job: find pending calls that ran out of time.
        Index(None, "status", "expires_at"),
        {"schema": DbSchema.AGENT},
    )

    # A call exists only as part of its run, so it goes with it (§IX-C).
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.runs.id", ondelete="CASCADE"))
    call_id: Mapped[str]
    tool: Mapped[str]
    arguments_fingerprint: Mapped[bytes]
    status: Mapped[PendingCallStatus] = mapped_column(text_enum(PendingCallStatus, "status"))
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expires_at: Mapped[datetime]
