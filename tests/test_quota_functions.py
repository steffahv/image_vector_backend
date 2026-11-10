"""The quota functions (migration 0014): the agent's only way to reserve, settle and release.

Calls run as the agent role (SET LOCAL ROLE), not as the superuser tests connect with: the
functions must work with exactly the rights the agent has. A call expected to fail runs inside
a savepoint, so the test can then check that nothing changed.
"""

import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import DBAPIError, ProgrammingError
from sqlalchemy.orm import Session

from app.agent.models import (
    Conversation,
    PeriodQuota,
    Reservation,
    ReservationStatus,
    Run,
    RunStatus,
)
from app.auth.models import AuthUser
from app.core.db import AGENT_ROLE, PLATFORM_ROLE, SessionLocal, set_current_account
from app.documents.models import Account, Document, Workspace
from tests.agent_factories import make_conversation, make_period_quota, make_run
from tests.conftest import as_role
from tests.factories import make_account, make_document, make_workspace

FUNCTIONS = (
    "agent.reserve_quota(uuid, text, bigint, timestamptz)",
    "agent.settle_reservation(uuid, bigint)",
    "agent.release_reservation(uuid)",
)
QUOTA = 100


@dataclass
class AgentTurn:
    account_id: uuid.UUID
    conversation: Conversation
    run: Run


@contextmanager
def _fails_with(db: Session, sqlstate: str) -> Iterator[None]:
    """The block fails with `sqlstate`, and everything it did is undone."""
    with pytest.raises(DBAPIError) as raised:
        with db.begin_nested():
            yield
    error = raised.value.orig
    assert getattr(error, "sqlstate", None) == sqlstate, error


def _reserve(db: Session, run_id: uuid.UUID, amount: int, resource: str = "tokens") -> uuid.UUID:
    reservation_id = db.scalar(
        text("SELECT agent.reserve_quota(:run, :resource, :amount, now() + interval '10 minutes')"),
        {"run": run_id, "resource": resource, "amount": amount},
    )
    assert isinstance(reservation_id, uuid.UUID)
    return reservation_id


def _settle(db: Session, reservation_id: uuid.UUID, used: int) -> None:
    db.execute(
        text("SELECT agent.settle_reservation(:id, :used)"), {"id": reservation_id, "used": used}
    )


def _release(db: Session, reservation_id: uuid.UUID) -> None:
    db.execute(text("SELECT agent.release_reservation(:id)"), {"id": reservation_id})


def _quota(db: Session, account_id: uuid.UUID) -> tuple[int, int]:
    """(reserved, consumed) of the account's tokens quota."""
    row = db.execute(
        select(PeriodQuota.reserved, PeriodQuota.consumed).where(
            PeriodQuota.account_id == account_id, PeriodQuota.resource == "tokens"
        )
    ).one()
    return row.reserved, row.consumed


def _status(db: Session, reservation_id: uuid.UUID) -> ReservationStatus:
    return db.scalars(select(Reservation.status).where(Reservation.id == reservation_id)).one()


def _turn(db: Session, account: Account) -> AgentTurn:
    """An active run of `account` with a tokens quota of QUOTA, created as the test user."""
    conversation = make_conversation(db, make_document(db, make_workspace(db, account)))
    run = make_run(db, conversation)
    make_period_quota(db, account.id, allocated=QUOTA)
    return AgentTurn(account.id, conversation, run)


def _act_as_agent(db: Session, account_id: uuid.UUID) -> None:
    as_role(db, AGENT_ROLE)
    set_current_account(db, account_id)


@pytest.fixture
def ana(db: Session, two_accounts: tuple[Account, Account]) -> AgentTurn:
    """Ana's turn; the session then acts as the agent for her."""
    turn = _turn(db, two_accounts[0])
    _act_as_agent(db, turn.account_id)
    return turn


# Reserving


def test_a_reservation_holds_part_of_the_quota(db: Session, ana: AgentTurn) -> None:
    reservation_id = _reserve(db, ana.run.id, 30)

    assert _quota(db, ana.account_id) == (30, 0)
    assert _status(db, reservation_id) == ReservationStatus.RESERVED


def test_a_reservation_cannot_pass_what_is_left(db: Session, ana: AgentTurn) -> None:
    _reserve(db, ana.run.id, 70)
    second_run = make_run(db, ana.conversation)

    with _fails_with(db, "VQ004"):
        _reserve(db, second_run.id, 31)
    assert _quota(db, ana.account_id) == (70, 0)

    _reserve(db, second_run.id, 30)  # exactly what is left
    assert _quota(db, ana.account_id) == (QUOTA, 0)


def test_a_retried_reservation_holds_the_amount_once(db: Session, ana: AgentTurn) -> None:
    first = _reserve(db, ana.run.id, 30)

    assert _reserve(db, ana.run.id, 30) == first
    assert _quota(db, ana.account_id) == (30, 0)


def test_a_retry_with_another_amount_is_refused(db: Session, ana: AgentTurn) -> None:
    _reserve(db, ana.run.id, 30)
    with _fails_with(db, "VQ005"):
        _reserve(db, ana.run.id, 50)
    assert _quota(db, ana.account_id) == (30, 0)


@pytest.mark.parametrize("amount", [0, -5])
def test_the_amount_must_be_positive(db: Session, ana: AgentTurn, amount: int) -> None:
    with _fails_with(db, "23514"):
        _reserve(db, ana.run.id, amount)


@pytest.mark.parametrize("status", [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.CANCELLED])
def test_a_finished_run_cannot_reserve(db: Session, ana: AgentTurn, status: RunStatus) -> None:
    db.execute(update(Run).where(Run.id == ana.run.id).values(status=status))
    with _fails_with(db, "VQ002"):
        _reserve(db, ana.run.id, 10)


def test_there_must_be_a_quota_in_force_for_the_resource(db: Session, ana: AgentTurn) -> None:
    with _fails_with(db, "VQ003"):
        _reserve(db, ana.run.id, 10, resource="images")


def test_an_expired_period_does_not_count(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    luis = two_accounts[1]
    conversation = make_conversation(db, make_document(db, make_workspace(db, luis)))
    run = make_run(db, conversation)
    ended = datetime.now(UTC) - timedelta(days=1)
    make_period_quota(db, luis.id, starts_at=ended - timedelta(days=30), ends_at=ended)
    _act_as_agent(db, luis.id)

    with _fails_with(db, "VQ003"):
        _reserve(db, run.id, 10)


def test_without_an_account_nothing_is_reserved(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    turn = _turn(db, two_accounts[0])
    as_role(db, AGENT_ROLE)

    with _fails_with(db, "VQ001"):
        _reserve(db, turn.run.id, 10)


# Settling and releasing


def test_settling_moves_what_was_used_to_consumed_and_gives_back_the_rest(
    db: Session, ana: AgentTurn
) -> None:
    reservation_id = _reserve(db, ana.run.id, 40)
    _settle(db, reservation_id, 25)

    assert _quota(db, ana.account_id) == (0, 25)
    assert _status(db, reservation_id) == ReservationStatus.SETTLED


def test_a_retried_settlement_does_not_charge_twice(db: Session, ana: AgentTurn) -> None:
    reservation_id = _reserve(db, ana.run.id, 40)
    _settle(db, reservation_id, 25)
    _settle(db, reservation_id, 25)

    assert _quota(db, ana.account_id) == (0, 25)


@pytest.mark.parametrize("used", [-1, 41])
def test_what_is_used_must_fit_in_the_reservation(db: Session, ana: AgentTurn, used: int) -> None:
    reservation_id = _reserve(db, ana.run.id, 40)
    with _fails_with(db, "23514"):
        _settle(db, reservation_id, used)
    assert _quota(db, ana.account_id) == (40, 0)


def test_releasing_gives_back_everything_once(db: Session, ana: AgentTurn) -> None:
    reservation_id = _reserve(db, ana.run.id, 40)
    _release(db, reservation_id)
    _release(db, reservation_id)

    assert _quota(db, ana.account_id) == (0, 0)
    assert _status(db, reservation_id) == ReservationStatus.RELEASED


def test_a_released_reservation_cannot_be_settled(db: Session, ana: AgentTurn) -> None:
    reservation_id = _reserve(db, ana.run.id, 40)
    _release(db, reservation_id)

    with _fails_with(db, "VQ005"):
        _settle(db, reservation_id, 10)
    assert _quota(db, ana.account_id) == (0, 0)


def test_a_settled_reservation_cannot_be_released(db: Session, ana: AgentTurn) -> None:
    reservation_id = _reserve(db, ana.run.id, 40)
    _settle(db, reservation_id, 10)

    with _fails_with(db, "VQ005"):
        _release(db, reservation_id)
    assert _quota(db, ana.account_id) == (0, 10)


# Between accounts


@pytest.fixture
def luis_reservation(db: Session, two_accounts: tuple[Account, Account]) -> AgentTurn:
    """Luis holds 40 of his quota; then the session acts as the agent for Ana."""
    ana, luis = two_accounts
    luis_turn = _turn(db, luis)
    _act_as_agent(db, luis.id)
    _reserve(db, luis_turn.run.id, 40)
    db.execute(text("RESET ROLE"))
    _turn(db, ana)
    _act_as_agent(db, ana.id)
    return luis_turn


def test_an_account_cannot_reserve_for_another_account_run(
    db: Session, luis_reservation: AgentTurn
) -> None:
    with _fails_with(db, "VQ002"):
        _reserve(db, luis_reservation.run.id, 10)


@pytest.mark.parametrize("action", ["settle", "release"])
def test_an_account_cannot_settle_or_release_another_account_reservation(
    db: Session, luis_reservation: AgentTurn, action: str
) -> None:
    db.execute(text("RESET ROLE"))
    reservation_id = db.scalars(
        select(Reservation.id).where(Reservation.run_id == luis_reservation.run.id)
    ).one()
    as_role(db, AGENT_ROLE)

    with _fails_with(db, "VQ005"):
        if action == "settle":
            _settle(db, reservation_id, 0)
        else:
            _release(db, reservation_id)

    db.execute(text("RESET ROLE"))
    assert _quota(db, luis_reservation.account_id) == (40, 0)


# Who may call them


def test_only_the_agent_may_call_the_quota_functions(db: Session) -> None:
    for signature in FUNCTIONS:
        for role, allowed in ((AGENT_ROLE, True), (PLATFORM_ROLE, False)):
            can = db.scalar(
                select(text(f"has_function_privilege('{role}', '{signature}', 'EXECUTE')"))
            )
            assert can is allowed, (role, signature)


def test_the_platform_gets_permission_denied(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    turn = _turn(db, two_accounts[0])
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, turn.account_id)

    with pytest.raises(ProgrammingError, match="permission denied for function reserve_quota"):
        _reserve(db, turn.run.id, 10)


def test_every_security_definer_function_fixes_its_search_path(db: Session) -> None:
    # A SECURITY DEFINER function runs with its owner's rights; without a fixed search_path a
    # caller could put its own table or function first and have it run with those rights.
    unsafe = db.scalars(
        text(
            "SELECT p.oid::regprocedure::text FROM pg_proc p"
            " JOIN pg_namespace n ON n.oid = p.pronamespace"
            " WHERE p.prosecdef AND n.nspname NOT IN ('pg_catalog', 'information_schema')"
            " AND NOT EXISTS (SELECT 1 FROM unnest(p.proconfig) c"
            "                 WHERE c = 'search_path=pg_catalog, pg_temp')"
        )
    ).all()
    assert unsafe == []


# Two runs at once: the lock on the quota makes the second one wait, then see the first.


def _committed_turn() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """An account with a quota of QUOTA and two active runs, committed. Returns the ids."""
    with SessionLocal() as db:
        account = make_account(db, f"{uuid.uuid4().hex}@example.com")
        conversation = make_conversation(db, make_document(db, make_workspace(db, account)))
        first, second = make_run(db, conversation), make_run(db, conversation)
        make_period_quota(db, account.id, allocated=QUOTA)
        db.commit()
        return account.id, first.id, second.id


def _delete_account(account_id: uuid.UUID) -> None:
    with SessionLocal() as db:
        user_id = db.scalars(select(Account.auth_user_id).where(Account.id == account_id)).one()
        workspace_ids = select(Workspace.id).where(Workspace.owner_id == account_id)
        for statement in (
            delete(Reservation).where(Reservation.account_id == account_id),
            delete(Run).where(Run.account_id == account_id),
            delete(PeriodQuota).where(PeriodQuota.account_id == account_id),
            delete(Conversation).where(Conversation.account_id == account_id),
            delete(Document).where(Document.workspace_id.in_(workspace_ids)),
            delete(Workspace).where(Workspace.owner_id == account_id),
            delete(Account).where(Account.id == account_id),
            delete(AuthUser).where(AuthUser.id == user_id),
        ):
            db.execute(statement)
        db.commit()


def test_two_runs_reserving_at_once_cannot_pass_the_quota_together() -> None:
    account_id, first_run, second_run = _committed_turn()
    errors: list[str | None] = []

    def reserve_in_parallel() -> None:
        with SessionLocal() as other:
            _act_as_agent(other, account_id)
            try:
                _reserve(other, second_run, 60)
                other.commit()
                errors.append(None)
            except DBAPIError as error:
                errors.append(getattr(error.orig, "sqlstate", None))

    try:
        with SessionLocal() as db:
            _act_as_agent(db, account_id)
            _reserve(db, first_run, 60)  # holds the lock on the quota row
            parallel = threading.Thread(target=reserve_in_parallel)
            parallel.start()
            time.sleep(0.5)
            assert parallel.is_alive(), "the second reservation did not wait for the first"
            db.commit()
        parallel.join(timeout=10)

        # 60 + 60 > 100: the second one waited, saw the first, and was refused.
        assert errors == ["VQ004"]
        with SessionLocal() as db:
            assert _quota(db, account_id) == (60, 0)
    finally:
        _delete_account(account_id)


def test_two_retries_of_a_reservation_at_once_return_the_same_one() -> None:
    # A request retried while the first try is still running: the lock on the run makes the
    # retry wait, then find the first reservation instead of failing on the unique key.
    account_id, run_id, _ = _committed_turn()
    results: list[uuid.UUID | str | None] = []

    def retry_in_parallel() -> None:
        with SessionLocal() as other:
            _act_as_agent(other, account_id)
            try:
                results.append(_reserve(other, run_id, 60))
                other.commit()
            except DBAPIError as error:
                results.append(getattr(error.orig, "sqlstate", None))

    try:
        with SessionLocal() as db:
            _act_as_agent(db, account_id)
            first = _reserve(db, run_id, 60)
            parallel = threading.Thread(target=retry_in_parallel)
            parallel.start()
            time.sleep(0.5)
            assert parallel.is_alive(), "the retry did not wait for the first try"
            db.commit()
        parallel.join(timeout=10)

        assert results == [first]
        with SessionLocal() as db:
            assert _quota(db, account_id) == (60, 0)
    finally:
        _delete_account(account_id)
