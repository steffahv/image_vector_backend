"""Reserve and settle through the agent role, including retries on a separate connection."""

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from queue import Queue
from time import monotonic, sleep

import pytest
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.agent.models import Conversation, Run, RunStatus
from app.auth.models import AuthUser
from app.billing.models import (
    CreditBalance,
    CreditMovement,
    CreditReservation,
    CreditReservationStatus,
)
from app.core.db import AGENT_ROLE, PLATFORM_ROLE, engine, set_current_account
from app.documents.models import Account, Document, Workspace
from tests.agent_factories import make_run
from tests.billing_factories import make_billable_run
from tests.conftest import as_role
from tests.factories import in_one_hour, make_account


def _wallet(db: Session, account: Account, **run_options: object) -> Run:
    run = make_billable_run(db, account, **run_options)
    db.add(CreditBalance(account_id=account.id, balance=100))
    db.flush()
    return run


def _reserve(db: Session, run_id: uuid.UUID, amount: int) -> uuid.UUID:
    reservation = db.scalar(select(func.billing.reserve_credits(run_id, amount, in_one_hour())))
    assert isinstance(reservation, uuid.UUID)
    return reservation


def _settle(db: Session, reservation_id: uuid.UUID, used: int) -> None:
    db.execute(select(func.billing.settle_credits(reservation_id, used)))


def _as_agent(db: Session, account_id: uuid.UUID) -> None:
    as_role(db, AGENT_ROLE)
    set_current_account(db, account_id)


def _balance(db: Session, account_id: uuid.UUID) -> tuple[int, int]:
    balance, reserved = db.execute(
        select(CreditBalance.balance, CreditBalance.reserved).where(
            CreditBalance.account_id == account_id
        )
    ).one()
    return balance, reserved


def test_settlement_retries_do_not_charge_twice(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    account_id, run_id = ana.id, _wallet(db, ana).id
    _as_agent(db, account_id)

    reservation_id = _reserve(db, run_id, 60)
    assert _reserve(db, run_id, 60) == reservation_id
    with pytest.raises(DBAPIError, match="conflicting credit reservation retry"), db.begin_nested():
        _reserve(db, run_id, 61)
    with pytest.raises(DBAPIError, match="invalid credit usage"), db.begin_nested():
        _settle(db, reservation_id, 61)

    _settle(db, reservation_id, 35)
    _settle(db, reservation_id, 35)
    with pytest.raises(DBAPIError, match="conflicting credit settlement retry"), db.begin_nested():
        _settle(db, reservation_id, 34)

    as_role(db, PLATFORM_ROLE)
    assert _balance(db, account_id) == (65, 0)
    assert db.scalar(select(CreditReservation.status)) == CreditReservationStatus.SETTLED
    assert db.execute(
        select(CreditMovement.amount, CreditMovement.reason, CreditMovement.reference)
    ).one() == (-35, "agent_usage", str(reservation_id))


def test_release_returns_the_whole_reservation_without_a_debit(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    account_id, run_id = ana.id, _wallet(db, ana).id
    _as_agent(db, account_id)
    reservation_id = _reserve(db, run_id, 100)
    _settle(db, reservation_id, 0)
    _settle(db, reservation_id, 0)
    with pytest.raises(DBAPIError, match="conflicting credit settlement retry"), db.begin_nested():
        _settle(db, reservation_id, 1)

    as_role(db, PLATFORM_ROLE)
    assert _balance(db, account_id) == (100, 0)
    assert db.scalar(select(CreditReservation.status)) == CreditReservationStatus.RELEASED
    assert db.scalar(select(func.count()).select_from(CreditMovement)) == 0


@pytest.mark.parametrize(
    ("amount", "expiry_offset", "status", "sqlstate"),
    [
        (101, 1, RunStatus.RUNNING, "VC003"),
        (0, 1, RunStatus.RUNNING, "VC004"),
        (5, -1, RunStatus.RUNNING, "VC004"),
        (5, 1, RunStatus.COMPLETED, "VC002"),
    ],
)
def test_failed_reservation_keeps_balance_and_rows_unchanged(
    db: Session,
    two_accounts: tuple[Account, Account],
    amount: int,
    expiry_offset: int,
    status: RunStatus,
    sqlstate: str,
) -> None:
    ana, _ = two_accounts
    account_id, run_id = ana.id, _wallet(db, ana, status=status).id
    _as_agent(db, account_id)
    expiry = datetime.now(UTC) + timedelta(hours=expiry_offset)

    with pytest.raises(DBAPIError) as exc, db.begin_nested():
        db.execute(select(func.billing.reserve_credits(run_id, amount, expiry)))
    assert exc.value.orig.sqlstate == sqlstate

    as_role(db, PLATFORM_ROLE)
    assert _balance(db, account_id) == (100, 0)
    assert db.scalar(select(func.count()).select_from(CreditReservation)) == 0


def test_agent_cannot_reserve_or_settle_for_another_account(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    ana_id, luis_id = ana.id, luis.id
    run_id = _wallet(db, luis).id
    as_role(db, AGENT_ROLE)
    with pytest.raises(DBAPIError, match="requires an account"), db.begin_nested():
        _reserve(db, run_id, 10)

    set_current_account(db, luis_id)
    reservation_id = _reserve(db, run_id, 10)
    set_current_account(db, ana_id)
    with pytest.raises(DBAPIError, match="credit run is unavailable"), db.begin_nested():
        _reserve(db, run_id, 10)
    with pytest.raises(DBAPIError, match="credit reservation is unavailable"), db.begin_nested():
        _settle(db, reservation_id, 0)

    as_role(db, PLATFORM_ROLE)
    set_current_account(db, luis_id)
    assert _balance(db, luis_id) == (100, 10)
    assert db.scalar(select(CreditReservation.status)) == CreditReservationStatus.RESERVED


@pytest.mark.parametrize(
    "statement",
    [
        "SELECT billing.reserve_credits(NULL, NULL, NULL)",
        "SELECT billing.settle_credits(NULL, NULL)",
    ],
)
def test_platform_cannot_execute_credit_functions(db: Session, statement: str) -> None:
    as_role(db, PLATFORM_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied for function"):
        db.execute(text(statement))


@pytest.mark.parametrize("same_run", [False, True])
def test_concurrent_reservations_use_the_committed_balance(same_run: bool) -> None:
    # The two agent transactions must see the same wallet, so setup is committed.
    with Session(engine) as setup:
        account = make_account(setup, f"{uuid.uuid4().hex}@example.com")
        first = _wallet(setup, account)
        conversation = setup.get_one(Conversation, first.conversation_id)
        second = make_run(setup, conversation)
        account_id, user_id = account.id, account.auth_user_id
        first_id, second_id = first.id, second.id
        workspace_id, document_id, conversation_id = (
            first.workspace_id,
            first.document_id,
            first.conversation_id,
        )
        setup.commit()

    backend_pid: Queue[int] = Queue()

    def reserve_on_second_connection() -> uuid.UUID:
        with Session(engine) as other:
            _as_agent(other, account_id)
            other.execute(text("SET LOCAL statement_timeout = '5s'"))
            backend_pid.put(other.scalars(select(func.pg_backend_pid())).one())
            reservation = _reserve(other, first_id if same_run else second_id, 60)
            other.commit()
            return reservation

    try:
        with ThreadPoolExecutor(max_workers=1) as worker, Session(engine) as db:
            _as_agent(db, account_id)
            first_reservation = _reserve(db, first_id, 60)
            pending = worker.submit(reserve_on_second_connection)
            pid = backend_pid.get(timeout=3)
            deadline = monotonic() + 3
            while not db.scalar(select(func.pg_blocking_pids(pid))):
                assert not pending.done(), "the second reservation did not wait"
                assert monotonic() < deadline, "the second reservation did not reach the lock"
                sleep(0.01)
            db.commit()

            if same_run:
                assert pending.result(timeout=5) == first_reservation
            else:
                with pytest.raises(DBAPIError) as insufficient:
                    pending.result(timeout=5)
                assert insufficient.value.orig.sqlstate == "VC003"

        with Session(engine) as observer:
            assert _balance(observer, account_id) == (100, 60)
            assert observer.scalars(
                select(CreditReservation.run_id).where(CreditReservation.account_id == account_id)
            ).all() == [first_id]
    finally:
        with Session(engine) as cleanup:
            cleanup.execute(
                delete(CreditReservation).where(CreditReservation.account_id == account_id)
            )
            cleanup.execute(delete(CreditBalance).where(CreditBalance.account_id == account_id))
            cleanup.execute(delete(Run).where(Run.id.in_((first_id, second_id))))
            cleanup.execute(delete(Conversation).where(Conversation.id == conversation_id))
            cleanup.execute(delete(Document).where(Document.id == document_id))
            cleanup.execute(delete(Workspace).where(Workspace.id == workspace_id))
            cleanup.execute(delete(Account).where(Account.id == account_id))
            cleanup.execute(delete(AuthUser).where(AuthUser.id == user_id))
            cleanup.commit()
