import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema


class PeriodQuota(Base):
    """How much of a resource an account may use in one period, and how much it has used.

    `period_id` names a cycle (its start and end are here); it is not a table of its own.
    The platform assigns quotas from the plan; the agent changes `reserved` and `consumed` only
    through the quota functions, never directly.
    """

    __tablename__ = "period_quotas"
    __table_args__ = (
        CheckConstraint("allocated >= 0", name="allocated_non_negative"),
        CheckConstraint("reserved >= 0", name="reserved_non_negative"),
        CheckConstraint("consumed >= 0", name="consumed_non_negative"),
        # What is held plus what was used never passes what was given, even under concurrency.
        CheckConstraint("reserved + consumed <= allocated", name="within_allocated"),
        CheckConstraint("ends_at > starts_at", name="ends_after_start"),
        {"schema": DbSchema.AGENT},
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform.accounts.id"), primary_key=True
    )
    period_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    resource: Mapped[str] = mapped_column(primary_key=True)
    starts_at: Mapped[datetime]
    ends_at: Mapped[datetime]
    allocated: Mapped[int] = mapped_column(BigInteger)
    reserved: Mapped[int] = mapped_column(BigInteger, server_default="0")
    consumed: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
