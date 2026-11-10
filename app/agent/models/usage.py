import uuid
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum


class UsageResult(StrEnum):
    """How the provider call that produced the usage ended."""

    SUCCESS = "success"
    ERROR = "error"
    CANCELLED = "cancelled"


NON_NEGATIVE_COLUMNS = (
    "input_tokens",
    "output_tokens",
    "units",
    "estimated_cost_micro",
    "duration_ms",
)


class Usage(UUIDPrimaryKey, CreatedAt, Base):
    """One usage event of a run (a provider call, an image...), with its estimated cost.

    Accounting record: it never changes and is not deleted with the run (§IX-C).
    """

    __tablename__ = "usage"
    __table_args__ = (
        # The same event is counted once, even if the agent retries recording it.
        UniqueConstraint("run_id", "event_id", "resource"),
        *(CheckConstraint(f"{c} >= 0", name=f"{c}_non_negative") for c in NON_NEGATIVE_COLUMNS),
        Index(None, "rate_id"),
        {"schema": DbSchema.AGENT},
    )

    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.runs.id"))
    rate_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("agent.rates.id"))
    event_id: Mapped[str]
    resource: Mapped[str]
    provider: Mapped[str]
    model: Mapped[str]
    input_tokens: Mapped[int] = mapped_column(BigInteger)
    output_tokens: Mapped[int] = mapped_column(BigInteger)
    units: Mapped[int] = mapped_column(BigInteger)
    estimated_cost_micro: Mapped[int] = mapped_column(BigInteger)
    charged: Mapped[bool]
    result: Mapped[UsageResult] = mapped_column(text_enum(UsageResult, "result"))
    duration_ms: Mapped[int] = mapped_column(BigInteger)
