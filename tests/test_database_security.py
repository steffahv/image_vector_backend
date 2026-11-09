"""Service roles, per-schema privileges and row-level security (migration 0010).

PostgreSQL skips RLS for superusers, and tests usually connect as one. So each test switches to
the role it checks with SET LOCAL ROLE, which also ends with the test's rolled-back transaction.
"""

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app import main
from app.auth.models import AuthUser
from app.core.config import get_settings
from app.core.db import (
    ACCOUNT_ID_SETTING,
    AGENT_ROLE,
    MIGRATOR_ROLE,
    PLATFORM_ROLE,
    USER_ID_SETTING,
    SessionLocal,
    check_app_role,
    set_current_account,
    set_current_user,
)
from app.documents.models import Account, AgentMode

SCHEMAS = ("auth", "platform", "storage", "billing", "agent", "operations")
AGENT_AUTH_TABLES = ("auth.users", "auth.sessions")
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


def test_an_account_cannot_insert_rows_for_another(db: Session) -> None:
    user = AuthUser(email="eva@example.com")
    db.add(user)
    db.flush()
    _as_role(db, PLATFORM_ROLE)
    set_current_account(db, uuid.uuid4())

    db.add(Account(auth_user_id=user.id, name="Eva", language="es", agent_mode=AgentMode.PLATFORM))
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.flush()


def test_sign_in_finds_the_account_of_the_signed_in_user(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    _as_role(db, PLATFORM_ROLE)
    set_current_user(db, ana.auth_user_id)

    assert _visible_account_ids(db) == {ana.id}


def test_sign_in_creates_the_account_the_first_time(db: Session) -> None:
    user = AuthUser(email="eva@example.com")
    db.add(user)
    db.flush()
    _as_role(db, PLATFORM_ROLE)
    set_current_user(db, user.id)

    db.add(Account(auth_user_id=user.id, name="Eva", language="es", agent_mode=AgentMode.PLATFORM))
    db.flush()


def test_the_signed_in_user_cannot_create_an_account_for_another_user(db: Session) -> None:
    eva, other = AuthUser(email="eva@example.com"), AuthUser(email="otro@example.com")
    db.add_all([eva, other])
    db.flush()
    _as_role(db, PLATFORM_ROLE)
    set_current_user(db, eva.id)

    db.add(
        Account(auth_user_id=other.id, name="Otro", language="es", agent_mode=AgentMode.PLATFORM)
    )
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.flush()


@pytest.mark.parametrize("column", ["id", "auth_user_id"])
def test_an_account_cannot_change_its_identity(
    db: Session, two_accounts: tuple[Account, Account], column: str
) -> None:
    ana, _ = two_accounts
    other_user = AuthUser(email="otro@example.com")
    db.add(other_user)
    db.flush()
    # Moving to another account's id or user: the trigger refuses before RLS is checked.
    new_value = uuid.uuid4() if column == "id" else other_user.id
    _as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    with pytest.raises(IntegrityError, match="cannot change its id or auth user"):
        db.execute(update(Account).where(Account.id == ana.id).values({column: new_value}))


def test_setting_the_account_ends_the_sign_in_lookup(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    _as_role(db, PLATFORM_ROLE)
    set_current_user(db, ana.auth_user_id)
    set_current_account(db, luis.id)

    assert _visible_account_ids(db) == {luis.id}


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


def test_the_account_survives_a_rolled_back_savepoint() -> None:
    account_id = uuid.uuid4()
    with SessionLocal() as db:
        db.scalar(select(1))
        savepoint = db.begin_nested()
        set_current_account(db, account_id)
        savepoint.rollback()

        assert _current_setting(db) == str(account_id)
        db.rollback()


def test_a_write_after_a_rolled_back_savepoint_has_the_account() -> None:
    account_id = uuid.uuid4()
    with SessionLocal() as db:
        db.scalar(select(1))
        savepoint = db.begin_nested()
        set_current_account(db, account_id)
        savepoint.rollback()

        db.add(AuthUser(email="eva@example.com"))
        db.flush()
        # Straight on the connection, so only the flush can have set it again.
        setting = db.connection().scalar(select(func.current_setting(ACCOUNT_ID_SETTING, True)))
        assert setting == str(account_id)
        db.rollback()


def test_a_cleared_user_stays_cleared_after_a_rolled_back_savepoint() -> None:
    with SessionLocal() as db:
        set_current_user(db, uuid.uuid4())
        db.scalar(select(1))
        savepoint = db.begin_nested()
        set_current_account(db, uuid.uuid4())  # clears the user
        savepoint.rollback()

        assert db.scalar(select(func.current_setting(USER_ID_SETTING, True))) in ("", None)
        db.rollback()


# Database user of the app (checked at startup outside development)


@pytest.mark.parametrize("role", [None, MIGRATOR_ROLE, AGENT_ROLE])
def test_the_app_refuses_a_user_that_skips_rls_or_is_not_the_platform(
    db: Session, role: str | None
) -> None:
    # None: the test user itself, a superuser.
    if role is not None:
        _as_role(db, role)
    with pytest.raises(RuntimeError, match="DATABASE_URL must be"):
        check_app_role(db.connection())


def test_the_app_does_not_start_in_production_as_a_superuser(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main.settings, "app_env", "production")
    with pytest.raises(RuntimeError, match="DATABASE_URL must be"):
        with TestClient(main.app):
            pass


def test_the_app_accepts_the_platform_role(db: Session) -> None:
    _as_role(db, PLATFORM_ROLE)
    check_app_role(db.connection())


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


def test_agent_reads_only_users_and_sessions_in_auth(db: Session) -> None:
    tables = _tables(db, ("auth",))
    assert set(AGENT_AUTH_TABLES) <= set(tables)
    for table in tables:
        expected = table in AGENT_AUTH_TABLES
        assert _has_privilege(db, AGENT_ROLE, table, "SELECT") == expected, table


def test_a_new_auth_table_is_not_readable_by_the_agent(db: Session) -> None:
    _as_role(db, MIGRATOR_ROLE)
    db.execute(text("CREATE TABLE auth.privileges_probe (id int)"))
    db.execute(text("RESET ROLE"))

    assert _has_privilege(db, PLATFORM_ROLE, "auth.privileges_probe", "INSERT")
    assert not _has_privilege(db, AGENT_ROLE, "auth.privileges_probe", "SELECT")


def test_a_new_function_is_executable_only_once_granted(db: Session) -> None:
    _as_role(db, MIGRATOR_ROLE)
    db.execute(
        text("CREATE FUNCTION agent.privileges_probe() RETURNS int LANGUAGE sql AS 'SELECT 1'")
    )
    db.execute(text("RESET ROLE"))
    probe = "agent.privileges_probe()"

    for role in (PLATFORM_ROLE, AGENT_ROLE):
        assert not db.scalar(select(func.has_function_privilege(role, probe, "EXECUTE"))), role

    db.execute(text(f"GRANT EXECUTE ON FUNCTION {probe} TO {AGENT_ROLE}"))
    assert db.scalar(select(func.has_function_privilege(AGENT_ROLE, probe, "EXECUTE")))
    assert not db.scalar(select(func.has_function_privilege(PLATFORM_ROLE, probe, "EXECUTE")))


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
