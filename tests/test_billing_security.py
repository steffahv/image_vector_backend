"""Check billing isolation as the real database roles, which cannot bypass FORCE RLS."""

from typing import Any

import pytest
from sqlalchemy import Table, delete, insert, select, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.billing.models import (
    CreditBalance,
    CreditMovement,
    CreditReservation,
    CreditReservationStatus,
    Plan,
    Subscription,
)
from app.core.db import AGENT_ROLE, MIGRATOR_ROLE, PLATFORM_ROLE, set_current_account
from app.core.model_base import Base
from app.documents.models import Account
from tests.billing_factories import make_billable_run, make_entitlement, make_subscription
from tests.conftest import as_role, has_privilege
from tests.factories import in_one_hour

ACCOUNT_TABLES = (Subscription, CreditBalance, CreditMovement, CreditReservation)


@pytest.fixture
def two_wallets(db: Session, two_accounts: tuple[Account, Account]) -> tuple[Account, Account]:
    plan = Plan(id="paid", name="Paid", active=True)
    db.add(plan)
    db.flush()
    entitlement = make_entitlement(db, plan)

    for account in two_accounts:
        run = make_billable_run(db, account)
        db.add(CreditBalance(account_id=account.id, balance=100, reserved=10))
        db.add(CreditMovement(account_id=account.id, amount=100, reason="purchase", reference="1"))
        db.add(
            CreditReservation(
                account_id=account.id,
                run_id=run.id,
                amount=10,
                status=CreditReservationStatus.RESERVED,
                expires_at=in_one_hour(),
            )
        )
        make_subscription(db, account, entitlement)
    return two_accounts


@pytest.mark.parametrize("role", [PLATFORM_ROLE, MIGRATOR_ROLE])
@pytest.mark.parametrize("model", ACCOUNT_TABLES)
def test_account_can_only_read_its_own_billing_rows(
    db: Session, two_wallets: tuple[Account, Account], role: str, model: Any
) -> None:
    ana, luis = two_wallets
    as_role(db, role)

    assert set(db.scalars(select(model.account_id))) == set()
    set_current_account(db, ana.id)
    assert set(db.scalars(select(model.account_id))) == {ana.id}
    set_current_account(db, luis.id)
    assert set(db.scalars(select(model.account_id))) == {luis.id}


@pytest.mark.parametrize("model", ACCOUNT_TABLES)
def test_rls_blocks_changing_or_removing_another_accounts_rows(
    db: Session, two_wallets: tuple[Account, Account], model: Any
) -> None:
    ana, luis = two_wallets
    # The owner can write these tables but must still obey FORCE RLS.
    as_role(db, MIGRATOR_ROLE)
    set_current_account(db, ana.id)

    others = model.account_id == luis.id
    assert db.execute(update(model).where(others).values(account_id=ana.id)).rowcount == 0
    assert db.execute(delete(model).where(others)).rowcount == 0
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.execute(update(model).values(account_id=luis.id))


def test_platform_cannot_open_a_wallet_directly(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(insert(CreditBalance).values(account_id=ana.id, balance=100))


def test_platform_cannot_change_another_accounts_subscription(
    db: Session, two_wallets: tuple[Account, Account]
) -> None:
    ana, luis = two_wallets
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    assert (
        db.execute(
            update(Subscription)
            .where(Subscription.account_id == luis.id)
            .values(cancel_at_period_end=True)
        ).rowcount
        == 0
    )
    assert db.execute(delete(Subscription).where(Subscription.account_id == luis.id)).rowcount == 0


def test_platform_cannot_insert_a_credit_movement_directly(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(
            insert(CreditMovement).values(
                account_id=ana.id, amount=10, reason="purchase", reference="payment-2"
            )
        )


@pytest.mark.parametrize("column", ["balance", "reserved"])
def test_platform_cannot_edit_a_balance_directly(
    db: Session, two_wallets: tuple[Account, Account], column: str
) -> None:
    ana, _ = two_wallets
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(update(CreditBalance).values({column: 200}))


@pytest.mark.parametrize("table", [t for t in Base.metadata.sorted_tables if t.schema == "billing"])
def test_agent_has_no_direct_access_to_billing_tables(db: Session, table: Table) -> None:
    for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
        assert not has_privilege(db, AGENT_ROLE, table.fullname, privilege)
    as_role(db, AGENT_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(select(table))
