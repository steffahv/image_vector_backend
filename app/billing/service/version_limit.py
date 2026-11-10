import uuid

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session

from app.billing.models import PlanEntitlement, Subscription, SubscriptionStatus

FREE_VERSION_LIMIT = 10


def version_limit(db: Session, account_id: uuid.UUID) -> int:
    """Read the best effective entitlement of the account already set in this transaction."""
    now = func.now()
    current_period = and_(
        Subscription.status.in_((SubscriptionStatus.ACTIVE, SubscriptionStatus.TRIALING)),
        now < Subscription.period_end,
    )
    grace_period = and_(
        Subscription.status == SubscriptionStatus.PAST_DUE,
        now < Subscription.grace_until,
    )
    limits = (
        select(func.max(PlanEntitlement.limits["max_versions"].as_integer()))
        .join(
            Subscription,
            and_(
                Subscription.plan_id == PlanEntitlement.plan_id,
                Subscription.entitlement_version == PlanEntitlement.version,
            ),
        )
        .where(
            Subscription.account_id == account_id,
            Subscription.period_start <= now,
            PlanEntitlement.effective_from <= now,
            or_(current_period, grace_period),
        )
    )
    limit: int | None = db.scalar(limits)
    return limit if limit is not None else FREE_VERSION_LIMIT
