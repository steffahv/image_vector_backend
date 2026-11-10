import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class ReservationStatus(StrEnum):
    """Lifecycle of a quota reservation (Modelo relacional §X: settled is used up)."""

    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"


class Reservation(UUIDPrimaryKey, Timestamps, Base):
    """Part of a period quota held by one run until it is settled or released."""

    __tablename__ = "reservations"
    __table_args__ = (
        UniqueConstraint("run_id", "resource"),
        # The run and the quota must both be of the reservation's account.
        ForeignKeyConstraint(
            ["account_id", "run_id"],
            ["agent.runs.account_id", "agent.runs.id"],
        ),
        ForeignKeyConstraint(
            ["account_id", "period_id", "resource"],
            [
                "agent.period_quotas.account_id",
                "agent.period_quotas.period_id",
                "agent.period_quotas.resource",
            ],
        ),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(None, "account_id", "period_id", "resource"),
        Index(None, "account_id", "run_id"),
        # Expiry job: release reservations whose run never finished.
        Index(None, "status", "expires_at"),
        {"schema": DbSchema.AGENT},
    )

    run_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    period_id: Mapped[uuid.UUID]
    resource: Mapped[str]
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[ReservationStatus] = mapped_column(text_enum(ReservationStatus, "status"))
    expires_at: Mapped[datetime]
