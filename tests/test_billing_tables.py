"""Exercise the relational constraints and the version limit through PostgreSQL."""

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session

from app.billing.models import (
    CreditBalance,
    CreditMovement,
    CreditPack,
    CreditReservation,
    CreditReservationStatus,
    GatewayEvent,
    GatewayEventStatus,
    Plan,
    PlanEntitlement,
    SubscriptionStatus,
)
from app.billing.service import version_limit
from app.core.db import PLATFORM_ROLE, set_current_account
from app.documents.models import Account
from tests.billing_factories import make_billable_run, make_entitlement, make_subscription
from tests.conftest import as_role
from tests.factories import in_one_hour


@pytest.mark.parametrize(("balance", "reserved"), [(10, 11), (10, -1), (-1, 0)])
def test_invalid_credit_balance_is_rejected(
    db: Session, two_accounts: tuple[Account, Account], balance: int, reserved: int
) -> None:
    with pytest.raises(IntegrityError, match="ck_credit_balances_within_balance"):
        db.execute(
            insert(CreditBalance).values(
                account_id=two_accounts[0].id, balance=balance, reserved=reserved
            )
        )


def test_gateway_retry_cannot_insert_the_same_event_twice(db: Session) -> None:
    as_role(db, PLATFORM_ROLE)
    event = insert(GatewayEvent).values(
        gateway="gateway-a",
        event_id="event-1",
        type="subscription.paid",
        payload={"payment": "paid"},
        status=GatewayEventStatus.PENDING,
    )
    db.execute(event)
    with pytest.raises(IntegrityError, match="uq_gateway_events_gateway_event_id"):
        db.execute(event)


@pytest.mark.parametrize("limits", [{}, {"max_versions": "50"}, {"max_versions": 0}, [50]])
def test_entitlement_limits_are_validated_by_database(db: Session, limits: object) -> None:
    db.add(Plan(id="paid", name="Paid", active=True))
    db.flush()
    with pytest.raises(IntegrityError, match="ck_plan_entitlements_limits_contract"):
        db.execute(
            insert(PlanEntitlement).values(
                plan_id="paid", version=1, effective_from=datetime.now(UTC), limits=limits
            )
        )


def test_entitlement_limits_are_validated_when_built() -> None:
    with pytest.raises(ValidationError, match="max_versions"):
        PlanEntitlement(limits={"max_versions": "50"})


def test_movement_reference_is_idempotent_per_account(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    movement = insert(CreditMovement).values(amount=10, reason="purchase", reference="payment-1")
    db.execute(movement.values(account_id=ana.id))
    db.execute(movement.values(account_id=luis.id))
    with pytest.raises(IntegrityError, match="uq_credit_movements_account_id_reason_reference"):
        db.execute(movement.values(account_id=ana.id))


@pytest.mark.parametrize(
    ("credits", "price", "constraint"),
    [(0, 100, "credits_positive"), (10, -1, "price_cents_non_negative")],
)
def test_invalid_credit_pack_is_rejected(
    db: Session, credits: int, price: int, constraint: str
) -> None:
    with pytest.raises(IntegrityError, match=f"ck_credit_packs_{constraint}"):
        db.execute(
            insert(CreditPack).values(
                credits=credits,
                price_cents=price,
                currency="USD",
                gateway="gateway-a",
                gateway_product_id="product-1",
                active=True,
            )
        )


def test_credit_reservation_cannot_point_to_another_accounts_run(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    run = make_billable_run(db, luis)

    with pytest.raises(IntegrityError, match="fk_credit_reservations_account_id_run_id_runs"):
        db.execute(
            insert(CreditReservation).values(
                account_id=ana.id,
                run_id=run.id,
                amount=5,
                status=CreditReservationStatus.RESERVED,
                expires_at=in_one_hour(),
            )
        )


def test_version_limit_is_pinned_and_cannot_read_another_account(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    plan = Plan(id="paid", name="Paid", active=True)
    db.add(plan)
    db.flush()
    original = make_entitlement(db, plan)
    make_subscription(db, luis, original)
    make_entitlement(db, plan, version=2, max_versions=30)

    as_role(db, PLATFORM_ROLE)
    assert version_limit(db, luis.id) == 10
    set_current_account(db, ana.id)
    assert version_limit(db, ana.id) == 10
    assert version_limit(db, luis.id) == 10
    set_current_account(db, luis.id)
    assert version_limit(db, luis.id) == 50


@pytest.mark.parametrize(
    ("status", "days_to_end", "days_to_grace", "expected"),
    [
        (SubscriptionStatus.ACTIVE, -1, None, 10),
        (SubscriptionStatus.PAST_DUE, -1, 1, 50),
        (SubscriptionStatus.PAST_DUE, -1, -1, 10),
        (SubscriptionStatus.TRIALING, 1, None, 50),
        (SubscriptionStatus.CANCELLED, 1, None, 10),
    ],
)
def test_version_limit_respects_subscription_period_and_grace(
    db: Session,
    two_accounts: tuple[Account, Account],
    status: SubscriptionStatus,
    days_to_end: int,
    days_to_grace: int | None,
    expected: int,
) -> None:
    ana, _ = two_accounts
    now = datetime.now(UTC)
    plan = Plan(id="paid", name="Paid", active=True)
    db.add(plan)
    db.flush()
    entitlement = make_entitlement(db, plan)
    make_subscription(
        db,
        ana,
        entitlement,
        status=status,
        period_start=now - timedelta(days=2),
        period_end=now + timedelta(days=days_to_end),
        grace_until=now + timedelta(days=days_to_grace) if days_to_grace is not None else None,
    )

    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)
    assert version_limit(db, ana.id) == expected


def test_platform_publishes_new_versions_instead_of_overwriting_rights(db: Session) -> None:
    plan = Plan(id="paid", name="Paid", active=True)
    db.add(plan)
    db.flush()
    make_entitlement(db, plan)
    as_role(db, PLATFORM_ROLE)

    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(update(PlanEntitlement).values(limits={"max_versions": 10}))
