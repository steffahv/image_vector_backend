"""Service roles, per-schema privileges and row-level security (migration 0010).

PostgreSQL skips RLS for superusers, and tests usually connect as one. So each test switches to
the role it checks with SET LOCAL ROLE, which also ends with the test's rolled-back transaction.
"""

import os
import uuid

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.auth.models import AuthUser
from app.core.config import get_settings
from app.core.db import (
    ACCOUNT_ID_SETTING,
    AGENT_ROLE,
    MIGRATOR_ROLE,
    PLATFORM_ROLE,
    SessionLocal,
    set_current_account,
)
from app.documents.models import Account, AgentMode

SCHEMAS = ("auth", "platform", "storage", "billing", "agent", "operations")
AGENT_READ_ONLY = ("auth", "platform")
AGENT_NO_ACCESS = ("storage", "billing", "operations")


def _as_role(db: Session, role: str) -> None:
    db.execute(text(f"SET LOCAL ROLE {role}"))


def _account(db: Session, email: str) -> Account:
    user = AuthUser(email=email)
    db.add(user)
    db.flush()
    account = Account(
        auth_user_id=user.id, name=email, language="es", agent_mode=AgentMode.PLATFORM
    )
    db.add(account)
    db.flush()
    return account


def _visible_account_ids(db: Session) -> set[uuid.UUID]:
    return set(db.scalars(select(Account.id)))


def _current_setting(db: Session) -> str | None:
    return db.scalar(select(func.current_setting(ACCOUNT_ID_SETTING, True)))


@pytest.fixture
def two_accounts(db: Session) -> tuple[Account, Account]:
    """Two accounts created as the test user, before switching to a restricted role."""
    return _account(db, "ana@example.com"), _account(db, "luis@example.com")


# Row-level security


@pytest.mark.parametrize("role", [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE])
def test_each_account_sees_only_itself(
    db: Session, two_accounts: tuple[Account, Account], role: str
) -> None:
    ana, luis = two_accounts
    _as_role(db, role)

    set_current_account(db, ana.id)
    assert _visible_account_ids(db) == {ana.id}

    set_current_account(db, luis.id)
    assert _visible_account_ids(db) == {luis.id}


def test_without_an_account_no_rows_are_visible(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    _as_role(db, PLATFORM_ROLE)
    assert _visible_account_ids(db) == set()


def test_an_account_cannot_change_or_delete_another(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    _as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    updated = db.execute(update(Account).where(Account.id == luis.id).values(name="hacked"))
    deleted = db.execute(text("DELETE FROM platform.accounts WHERE id = :id"), {"id": luis.id})

    assert updated.rowcount == 0
    assert deleted.rowcount == 0


def test_an_account_cannot_move_its_row_to_another(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    _as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    with pytest.raises(ProgrammingError, match="row-level security"):
        db.execute(update(Account).where(Account.id == ana.id).values(id=luis.id))


def test_an_account_cannot_insert_rows_for_another(db: Session) -> None:
    user = AuthUser(email="eva@example.com")
    db.add(user)
    db.flush()
    _as_role(db, PLATFORM_ROLE)
    set_current_account(db, uuid.uuid4())

    db.add(Account(auth_user_id=user.id, name="Eva", language="es", agent_mode=AgentMode.PLATFORM))
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.flush()


# Identity per transaction


def test_the_account_is_kept_across_commits_of_the_same_session() -> None:
    account_id = uuid.uuid4()
    with SessionLocal() as db:
        set_current_account(db, account_id)
        assert _current_setting(db) == str(account_id)
        db.commit()
        assert _current_setting(db) == str(account_id)

        set_current_account(db, None)
        assert _current_setting(db) in ("", None)


def test_the_account_does_not_leak_to_the_next_request_on_the_same_connection() -> None:
    # A pool of one connection, so the second request is sure to reuse the first one's.
    single_connection = create_engine(get_settings().database_url, pool_size=1, max_overflow=0)
    sessions = sessionmaker(bind=single_connection)
    try:
        with sessions() as first_request:
            set_current_account(first_request, uuid.uuid4())
            first_pid = first_request.scalar(select(func.pg_backend_pid()))
            first_request.commit()

        with sessions() as next_request:
            assert next_request.scalar(select(func.pg_backend_pid())) == first_pid
            assert _current_setting(next_request) in ("", None)
    finally:
        single_connection.dispose()


# Privileges per schema


def _tables(db: Session, schemas: tuple[str, ...]) -> list[str]:
    return list(
        db.scalars(
            text(
                "SELECT schemaname || '.' || tablename FROM pg_tables "
                "WHERE schemaname = ANY(:schemas)"
            ),
            {"schemas": list(schemas)},
        )
    )


def _has_privilege(db: Session, role: str, table: str, privilege: str) -> bool:
    return bool(
        db.scalar(
            select(func.has_table_privilege(role, table, privilege)),
        )
    )


def test_agent_cannot_write_platform_storage_or_billing(db: Session) -> None:
    tables = _tables(db, ("auth", "platform", "storage", "billing", "operations"))
    assert tables, "no tables to check: is the database migrated?"
    for table in tables:
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not _has_privilege(db, AGENT_ROLE, table, privilege), (table, privilege)


def test_agent_write_is_refused_by_the_database(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    _as_role(db, AGENT_ROLE)
    set_current_account(db, ana.id)

    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(update(Account).where(Account.id == ana.id).values(name="changed"))


def test_agent_has_no_access_to_storage_billing_or_operations(db: Session) -> None:
    for schema in AGENT_NO_ACCESS:
        assert not db.scalar(select(func.has_schema_privilege(AGENT_ROLE, schema, "USAGE"))), schema


def test_only_the_migrator_can_create_tables(db: Session) -> None:
    for schema in SCHEMAS:
        for role in (PLATFORM_ROLE, AGENT_ROLE):
            assert not db.scalar(select(func.has_schema_privilege(role, schema, "CREATE"))), (
                role,
                schema,
            )


def test_every_table_is_owned_by_the_migrator(db: Session) -> None:
    owners = dict(
        db.execute(
            text(
                "SELECT schemaname || '.' || tablename, tableowner FROM pg_tables "
                "WHERE schemaname = ANY(:schemas)"
            ),
            {"schemas": list(SCHEMAS)},
        )
        .tuples()
        .all()
    )
    assert {table: owner for table, owner in owners.items() if owner != MIGRATOR_ROLE} == {}


def test_a_new_table_gets_its_privileges_with_no_manual_step(db: Session) -> None:
    _as_role(db, MIGRATOR_ROLE)
    db.execute(text("CREATE TABLE platform.privileges_probe (id int)"))
    db.execute(text("CREATE TABLE agent.privileges_probe (id int)"))
    db.execute(text("RESET ROLE"))

    assert _has_privilege(db, PLATFORM_ROLE, "platform.privileges_probe", "INSERT")
    assert _has_privilege(db, AGENT_ROLE, "platform.privileges_probe", "SELECT")
    assert not _has_privilege(db, AGENT_ROLE, "platform.privileges_probe", "INSERT")
    assert _has_privilege(db, AGENT_ROLE, "agent.privileges_probe", "INSERT")
    assert _has_privilege(db, PLATFORM_ROLE, "agent.privileges_probe", "SELECT")
    assert not _has_privilege(db, PLATFORM_ROLE, "agent.privileges_probe", "INSERT")


# Real login users (created in CI by scripts/create_login_roles.sql)


@pytest.mark.skipif(
    "AGENT_DATABASE_URL" not in os.environ, reason="AGENT_DATABASE_URL is not set (set in CI)"
)
def test_agent_login_user_inherits_the_agent_role() -> None:
    agent_engine = create_engine(os.environ["AGENT_DATABASE_URL"])
    try:
        with agent_engine.connect() as connection:
            assert connection.scalar(select(func.pg_has_role(AGENT_ROLE, "MEMBER")))
            with pytest.raises(ProgrammingError, match="permission denied"):
                connection.execute(text("DELETE FROM platform.accounts"))
    finally:
        agent_engine.dispose()
