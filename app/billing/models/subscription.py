import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class SubscriptionStatus(StrEnum):
    ACTIVE = "active"
    TRIALING = "trialing"
    PAST_DUE = "past_due"
    CANCELLED = "cancelled"


class Subscription(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        ForeignKeyConstraint(
            ["plan_id", "entitlement_version"],
            ["billing.plan_entitlements.plan_id", "billing.plan_entitlements.version"],
        ),
        UniqueConstraint("gateway", "gateway_subscription_id"),
        CheckConstraint("period_end > period_start", name="period_order"),
        Index(None, "account_id", "status"),
        Index(None, "plan_id", "entitlement_version"),
        {"schema": DbSchema.BILLING},
    )

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"))
    plan_id: Mapped[str]
    entitlement_version: Mapped[int]
    gateway: Mapped[str]
    gateway_subscription_id: Mapped[str]
    status: Mapped[SubscriptionStatus] = mapped_column(text_enum(SubscriptionStatus, "status"))
    period_start: Mapped[datetime]
    period_end: Mapped[datetime]
    cancel_at_period_end: Mapped[bool]
    grace_until: Mapped[datetime | None]
