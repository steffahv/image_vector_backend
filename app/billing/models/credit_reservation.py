import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class CreditReservationStatus(StrEnum):
    RESERVED = "reserved"
    SETTLED = "settled"
    RELEASED = "released"


class CreditReservation(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "credit_reservations"
    __table_args__ = (
        ForeignKeyConstraint(["account_id", "run_id"], ["agent.runs.account_id", "agent.runs.id"]),
        CheckConstraint("amount > 0", name="amount_positive"),
        Index(None, "account_id"),
        Index(None, "status", "expires_at"),
        {"schema": DbSchema.BILLING},
    )

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"))
    run_id: Mapped[uuid.UUID] = mapped_column(unique=True)
    amount: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[CreditReservationStatus] = mapped_column(
        text_enum(CreditReservationStatus, "status")
    )
    expires_at: Mapped[datetime]
