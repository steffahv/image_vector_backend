"""Build billing rows with the same account and run relationships as production."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.agent.models import Run
from app.billing.models import Plan, PlanEntitlement, Subscription, SubscriptionStatus
from app.documents.models import Account
from tests.agent_factories import make_conversation, make_run
from tests.factories import make_document, make_workspace


def make_billable_run(db: Session, account: Account, **overrides: object) -> Run:
    document = make_document(db, make_workspace(db, account))
    return make_run(db, make_conversation(db, document), **overrides)


def make_entitlement(
    db: Session, plan: Plan, version: int = 1, max_versions: int = 50
) -> PlanEntitlement:
    entitlement = PlanEntitlement(
        plan_id=plan.id,
        version=version,
        effective_from=datetime.now(UTC) - timedelta(days=1),
        limits={"max_versions": max_versions},
    )
    db.add(entitlement)
    db.flush()
    return entitlement


def make_subscription(
    db: Session, account: Account, entitlement: PlanEntitlement, **overrides: object
) -> Subscription:
    now = datetime.now(UTC)
    values: dict[str, object] = {
        "account_id": account.id,
        "plan_id": entitlement.plan_id,
        "entitlement_version": entitlement.version,
        "gateway": "gateway-a",
        "gateway_subscription_id": str(uuid.uuid4()),
        "status": SubscriptionStatus.ACTIVE,
        "period_start": now - timedelta(days=1),
        "period_end": now + timedelta(days=30),
        "cancel_at_period_end": False,
    }
    subscription = Subscription(**(values | overrides))
    db.add(subscription)
    db.flush()
    return subscription
