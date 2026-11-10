"""Row-level security and privileges of the agent and operations tables (migration 0013).

The tables with a workspace_id (conversations, runs) are in the generic workspace tests of
tests/test_database_security.py. Here are the ones that follow their parent (messages, calls,
usage), belong to an account directly (quotas, reservations), or have their own rules (object
copies, the audit log, rates).

PostgreSQL skips RLS for superusers, and tests connect as one. So each test switches to the role
it checks with SET LOCAL ROLE, which ends with the test's rolled-back transaction.
"""

import json
import uuid
from dataclasses import dataclass

import pytest
from sqlalchemy import func, insert, select, text
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session

from app.agent.models import Conversation, Rate
from app.core.db import AGENT_ROLE, MIGRATOR_ROLE, PLATFORM_ROLE, set_current_account
from app.documents.models import Account, Document
from app.jobs.models import AuditEntry, AuditResult
from tests.agent_factories import (
    make_audit_entry,
    make_conversation,
    make_message,
    make_object_copy,
    make_pending_call,
    make_period_quota,
    make_rate,
    make_reservation,
    make_run,
    make_usage,
)
from tests.conftest import as_role, has_privilege
from tests.factories import make_document, make_object, make_workspace


@dataclass
class AgentRows:
    """The keys of one account's rows, as each table points to its owner."""

    account_id: uuid.UUID
    workspace_id: uuid.UUID
    document_id: uuid.UUID
    conversation_id: uuid.UUID
    run_id: uuid.UUID
    object_id: uuid.UUID


def _fill_agent_tables(db: Session, account: Account, rate: Rate) -> AgentRows:
    """One row of the account in every table of OWNER_KEYS, and an audit entry."""
    workspace = make_workspace(db, account)
    document = make_document(db, workspace)
    conversation = make_conversation(db, document)
    make_message(db, conversation)
    run = make_run(db, conversation)
    make_pending_call(db, run)
    make_usage(db, run, rate)
    make_reservation(db, run, make_period_quota(db, account.id))
    stored = make_object(db, workspace)
    make_object_copy(db, stored)
    make_audit_entry(db, workspace.id)
    return AgentRows(account.id, workspace.id, document.id, conversation.id, run.id, stored.id)


@pytest.fixture
def two_owners(db: Session, two_accounts: tuple[Account, Account]) -> tuple[AgentRows, AgentRows]:
    """Ana's and Luis's rows, created as the test user before switching role."""
    ana, luis = two_accounts
    rate = make_rate(db)
    return _fill_agent_tables(db, ana, rate), _fill_agent_tables(db, luis, rate)


# The column that ties each row to its account, and the field of AgentRows with its value.
OWNER_KEYS = {
    "agent.messages": ("conversation_id", "conversation_id"),
    "agent.pending_calls": ("run_id", "run_id"),
    "agent.usage": ("run_id", "run_id"),
    "agent.period_quotas": ("account_id", "account_id"),
    "agent.reservations": ("account_id", "account_id"),
    "operations.object_copies": ("object_id", "object_id"),
}

# Who may do what on each table, as granted by migrations 0010 and 0013. The agent changes
# quotas and reservations only through the quota functions; usage is written once.
READERS = {
    "agent.messages": [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE],
    "agent.pending_calls": [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE],
    "agent.usage": [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE],
    "agent.period_quotas": [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE],
    "agent.reservations": [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE],
    "operations.object_copies": [PLATFORM_ROLE, MIGRATOR_ROLE],
}
INSERTERS = {
    "agent.messages": [AGENT_ROLE, MIGRATOR_ROLE],
    "agent.pending_calls": [AGENT_ROLE, MIGRATOR_ROLE],
    "agent.usage": [AGENT_ROLE, MIGRATOR_ROLE],
    "agent.period_quotas": [PLATFORM_ROLE, MIGRATOR_ROLE],
    "agent.reservations": [MIGRATOR_ROLE],
    "operations.object_copies": [PLATFORM_ROLE, MIGRATOR_ROLE],
}
UPDATERS = INSERTERS | {"agent.usage": [MIGRATOR_ROLE]}
DELETERS = UPDATERS | {"agent.period_quotas": [MIGRATOR_ROLE]}


def _cases(roles_by_table: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(table, role) for table, roles in roles_by_table.items() for role in roles]


def _act_for(db: Session, rows: AgentRows, role: str) -> None:
    as_role(db, role)
    set_current_account(db, rows.account_id)


def _owner_values(db: Session, table: str) -> set[uuid.UUID]:
    # `table` and its column come from OWNER_KEYS, constants of this file.
    column, _ = OWNER_KEYS[table]
    return set(db.scalars(text(f"SELECT {column} FROM {table}")))


def _owner_value(rows: AgentRows, table: str) -> uuid.UUID:
    _, field = OWNER_KEYS[table]
    value: uuid.UUID = getattr(rows, field)
    return value


@pytest.mark.parametrize(("table", "role"), _cases(READERS))
def test_each_account_sees_only_its_own_agent_rows(
    db: Session, two_owners: tuple[AgentRows, AgentRows], table: str, role: str
) -> None:
    ana, _ = two_owners
    _act_for(db, ana, role)
    assert _owner_values(db, table) == {_owner_value(ana, table)}


@pytest.mark.parametrize("table", OWNER_KEYS)
def test_without_an_account_no_agent_rows_are_visible(
    db: Session, two_owners: tuple[AgentRows, AgentRows], table: str
) -> None:
    as_role(db, PLATFORM_ROLE)
    assert _owner_values(db, table) == set()


@pytest.mark.parametrize(("table", "role"), _cases(UPDATERS))
def test_an_account_cannot_change_another_account_agent_rows(
    db: Session, two_owners: tuple[AgentRows, AgentRows], table: str, role: str
) -> None:
    ana, luis = two_owners
    column, _ = OWNER_KEYS[table]
    _act_for(db, ana, role)

    updated = db.execute(
        text(f"UPDATE {table} SET {column} = {column} WHERE {column} = :luis"),
        {"luis": _owner_value(luis, table)},
    )
    assert updated.rowcount == 0


@pytest.mark.parametrize(("table", "role"), _cases(DELETERS))
def test_an_account_cannot_delete_another_account_agent_rows(
    db: Session, two_owners: tuple[AgentRows, AgentRows], table: str, role: str
) -> None:
    ana, luis = two_owners
    column, _ = OWNER_KEYS[table]
    _act_for(db, ana, role)

    deleted = db.execute(
        text(f"DELETE FROM {table} WHERE {column} = :luis"), {"luis": _owner_value(luis, table)}
    )
    assert deleted.rowcount == 0


@pytest.mark.parametrize(("table", "role"), _cases(INSERTERS))
def test_an_account_cannot_insert_agent_rows_for_another(
    db: Session, two_owners: tuple[AgentRows, AgentRows], table: str, role: str
) -> None:
    ana, luis = two_owners
    column, _ = OWNER_KEYS[table]
    # A copy of Ana's row pointed at Luis. PostgreSQL checks the policy before keys and CHECKs.
    row = db.scalar(
        text(f"SELECT to_jsonb(t) FROM {table} t WHERE {column} = :ana"),
        {"ana": _owner_value(ana, table)},
    )
    assert row is not None
    row[column] = str(_owner_value(luis, table))
    _act_for(db, ana, role)

    with pytest.raises(ProgrammingError, match="row-level security policy"):
        db.execute(
            text(
                f"INSERT INTO {table}"
                f" SELECT * FROM jsonb_populate_record(NULL::{table}, CAST(:row AS jsonb))"
            ),
            {"row": json.dumps(row)},
        )


@pytest.mark.parametrize("model", ["conversation", "run"])
def test_a_conversation_or_run_cannot_be_filed_under_another_account(
    db: Session, two_owners: tuple[AgentRows, AgentRows], model: str
) -> None:
    # Ana's own workspace and document, but Luis's account: the policy refuses it.
    ana, luis = two_owners
    document = db.get_one(Document, ana.document_id)
    conversation = db.get_one(Conversation, ana.conversation_id)
    _act_for(db, ana, AGENT_ROLE)

    with pytest.raises(ProgrammingError, match="row-level security policy"):
        if model == "conversation":
            make_conversation(db, document, account_id=luis.account_id)
        else:
            make_run(db, conversation, account_id=luis.account_id)


# What each role may do beyond the schema defaults (migration 0013)


@pytest.mark.parametrize(
    "statement",
    [
        "INSERT INTO agent.period_quotas SELECT * FROM agent.period_quotas",
        "UPDATE agent.period_quotas SET reserved = reserved + 1",
        "UPDATE agent.reservations SET amount = amount + 1",
        "INSERT INTO agent.reservations SELECT * FROM agent.reservations",
        "UPDATE agent.usage SET estimated_cost_micro = 0",
        "DELETE FROM agent.usage",
        "UPDATE agent.rates SET input_price_micro = 0",
        "INSERT INTO agent.rates SELECT * FROM agent.rates",
    ],
)
def test_the_agent_cannot_touch_quotas_prices_or_past_usage_directly(
    db: Session, two_owners: tuple[AgentRows, AgentRows], statement: str
) -> None:
    ana, _ = two_owners
    _act_for(db, ana, AGENT_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(text(statement))


def test_the_agent_reads_its_quotas_and_the_prices(
    db: Session, two_owners: tuple[AgentRows, AgentRows]
) -> None:
    ana, _ = two_owners
    _act_for(db, ana, AGENT_ROLE)

    assert db.scalar(text("SELECT count(*) FROM agent.period_quotas")) == 1
    # Prices are global: no account needed to read them.
    assert db.scalar(select(Rate.provider)) == "provider-a"


def test_the_platform_assigns_quotas_and_adds_prices_but_does_not_rewrite_them(
    db: Session,
) -> None:
    for privilege in ("INSERT", "UPDATE"):
        assert has_privilege(db, PLATFORM_ROLE, "agent.period_quotas", privilege)
    assert not has_privilege(db, PLATFORM_ROLE, "agent.period_quotas", "DELETE")
    assert has_privilege(db, PLATFORM_ROLE, "agent.rates", "INSERT")
    for privilege in ("UPDATE", "DELETE"):
        assert not has_privilege(db, PLATFORM_ROLE, "agent.rates", privilege)
    # Everything else in agent stays read-only for the platform.
    for table in ("agent.conversations", "agent.runs", "agent.reservations", "agent.usage"):
        assert not has_privilege(db, PLATFORM_ROLE, table, "INSERT"), table


def test_the_platform_assigns_a_quota_to_its_own_account(
    db: Session, two_owners: tuple[AgentRows, AgentRows]
) -> None:
    ana, luis = two_owners
    _act_for(db, ana, PLATFORM_ROLE)

    make_period_quota(db, ana.account_id, resource="images")
    with pytest.raises(ProgrammingError, match="row-level security policy"):
        make_period_quota(db, luis.account_id, resource="images")


# Audit log: anyone may add an entry, nobody may change or delete one.


def _add_audit_entry(db: Session, workspace_id: uuid.UUID | None) -> None:
    # As the app must write them: without RETURNING (see AuditEntry).
    db.execute(
        insert(AuditEntry).values(
            workspace_id=workspace_id,
            action="sign_in",
            entity_type="session",
            result=AuditResult.DENIED,
        )
    )


def test_an_audit_entry_can_be_added_with_no_account(db: Session) -> None:
    # A failed sign-in or an anonymous share link has no account yet.
    workspace = make_workspace(db)
    as_role(db, PLATFORM_ROLE)

    _add_audit_entry(db, workspace.id)
    _add_audit_entry(db, None)

    db.execute(text("RESET ROLE"))
    assert db.scalar(select(func.count()).select_from(AuditEntry)) == 2


def test_an_audit_entry_cannot_be_read_back_with_no_account(db: Session) -> None:
    # RETURNING counts as reading the new row, which a session with no account may not do.
    as_role(db, PLATFORM_ROLE)
    with pytest.raises(ProgrammingError, match="row-level security policy"):
        make_audit_entry(db, None)


def test_each_account_reads_only_its_own_audit_entries(
    db: Session, two_owners: tuple[AgentRows, AgentRows]
) -> None:
    ana, _ = two_owners
    make_audit_entry(db, None)
    _act_for(db, ana, PLATFORM_ROLE)

    assert set(db.scalars(select(AuditEntry.workspace_id))) == {ana.workspace_id}


@pytest.mark.parametrize(
    "statement",
    ["UPDATE operations.audit_log SET result = 'success'", "DELETE FROM operations.audit_log"],
)
def test_nobody_rewrites_the_audit_log(
    db: Session, two_owners: tuple[AgentRows, AgentRows], statement: str
) -> None:
    ana, _ = two_owners
    _act_for(db, ana, PLATFORM_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(text(statement))


@pytest.mark.parametrize(
    "table", ["operations.audit_log", "operations.object_copies", "operations.backup_runs"]
)
def test_the_agent_gets_permission_denied_on_operations(db: Session, table: str) -> None:
    as_role(db, AGENT_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied for schema operations"):
        db.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


def test_a_conversation_of_the_agent_is_visible_to_the_platform(
    db: Session, two_owners: tuple[AgentRows, AgentRows]
) -> None:
    # The platform shows the history: it reads agent rows of the account it acts for.
    ana, _ = two_owners
    _act_for(db, ana, PLATFORM_ROLE)
    assert set(db.scalars(select(Conversation.id))) == {ana.conversation_id}
