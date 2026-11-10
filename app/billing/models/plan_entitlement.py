from datetime import datetime

from pydantic import JsonValue
from sqlalchemy import CheckConstraint, ForeignKey
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, validates

from app.billing.schemas.plan_limits import PlanLimits
from app.core.model_base import Base, CreatedAt, DbSchema


class PlanEntitlement(CreatedAt, Base):
    """A version of the limits to which a subscription is pinned."""

    __tablename__ = "plan_entitlements"
    __table_args__ = (
        CheckConstraint("version > 0", name="version_positive"),
        CheckConstraint(
            "coalesce(jsonb_typeof(limits) = 'object'"
            " AND jsonb_typeof(limits->'max_versions') = 'number'"
            " AND (limits->>'max_versions') ~ '^[1-9][0-9]*$'"
            " AND (limits->'max_versions') <= '2147483647'::jsonb, false)",
            name="limits_contract",
        ),
        {"schema": DbSchema.BILLING},
    )

    plan_id: Mapped[str] = mapped_column(ForeignKey("billing.plans.id"), primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    effective_from: Mapped[datetime]
    limits: Mapped[dict[str, JsonValue]] = mapped_column(JSONB)

    @validates("limits")
    def validate_limits(self, _key: str, limits: dict[str, JsonValue]) -> dict[str, JsonValue]:
        PlanLimits.model_validate(limits)
        return limits
