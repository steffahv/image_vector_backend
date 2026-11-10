from datetime import datetime
from enum import StrEnum

from pydantic import JsonValue
from sqlalchemy import UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum


class GatewayEventStatus(StrEnum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


class GatewayEvent(UUIDPrimaryKey, CreatedAt, Base):
    """A platform-only inbox entry, possibly received before the account is known."""

    __tablename__ = "gateway_events"
    __table_args__ = (UniqueConstraint("gateway", "event_id"), {"schema": DbSchema.BILLING})

    gateway: Mapped[str]
    event_id: Mapped[str]
    type: Mapped[str]
    payload: Mapped[JsonValue] = mapped_column(JSONB, nullable=False)
    status: Mapped[GatewayEventStatus] = mapped_column(text_enum(GatewayEventStatus, "status"))
    processed_at: Mapped[datetime | None]
    error_code: Mapped[str | None]
