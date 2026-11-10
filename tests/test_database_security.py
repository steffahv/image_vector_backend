"""Service roles, per-schema privileges and row-level security (migrations 0010, 0012, 0013).

The agent tables without a workspace_id are in tests/test_agent_security.py.

PostgreSQL skips RLS for superusers, and tests usually connect as one. So each test switches to
the role it checks with SET LOCAL ROLE, which also ends with the test's rolled-back transaction.
"""

import json
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
from app.documents.models import (
    Account,
    AgentMode,
    DocumentRevision,
    DocumentVersion,
    Folder,
    RevisionImage,
    VersionSource,
    Workspace,
    WorkspaceType,
)
from app.storage.models import (
    ByteReservation,
    ByteReservationStatus,
    ObjectKind,
)
from tests.agent_factories import make_conversation, make_run
from tests.conftest import as_role, has_privilege
from tests.factories import (
    in_one_hour,
    make_document,
    make_object,
    make_quota,
    make_revision,
    make_save,
    make_share_link,
    make_upload,
    make_workspace,
)

SCHEMAS = ("auth", "platform", "storage", "billing", "agent", "operations")
AGENT_AUTH_TABLES = ("auth.users", "auth.sessions")
AGENT_NO_ACCESS = ("storage", "operations")


def _visible_account_ids(db: Session) -> set[uuid.UUID]:
    return set(db.scalars(select(Account.id)))


def _current_setting(db: Session) -> str | None:
    return db.scalar(select(func.current_setting(ACCOUNT_ID_SETTING, True)))


# Row-level security


@pytest.mark.parametrize("role", [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE])
def test_each_account_sees_only_itself(
    db: Session, two_accounts: tuple[Account, Account], role: str
) -> None:
    ana, luis = two_accounts
    as_role(db, role)

    set_current_account(db, ana.id)
    assert _visible_account_ids(db) == {ana.id}

    set_current_account(db, luis.id)
    assert _visible_account_ids(db) == {luis.id}


def test_without_an_account_no_rows_are_visible(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    as_role(db, PLATFORM_ROLE)
    assert _visible_account_ids(db) == set()


def test_an_account_cannot_change_or_delete_another(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    updated = db.execute(update(Account).where(Account.id == luis.id).values(name="hacked"))
    deleted = db.execute(text("DELETE FROM platform.accounts WHERE id = :id"), {"id": luis.id})

    assert updated.rowcount == 0
    assert deleted.rowcount == 0


def test_an_account_cannot_insert_rows_for_another(db: Session) -> None:
    user = AuthUser(email="eva@example.com")
    db.add(user)
    db.flush()
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, uuid.uuid4())

    db.add(Account(auth_user_id=user.id, name="Eva", language="es", agent_mode=AgentMode.PLATFORM))
    with pytest.raises(ProgrammingError, match="row-level security"):
        db.flush()


def test_sign_in_finds_the_account_of_the_signed_in_user(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    as_role(db, PLATFORM_ROLE)
    set_current_user(db, ana.auth_user_id)

    assert _visible_account_ids(db) == {ana.id}


def test_sign_in_creates_the_account_the_first_time(db: Session) -> None:
    user = AuthUser(email="eva@example.com")
    db.add(user)
    db.flush()
    as_role(db, PLATFORM_ROLE)
    set_current_user(db, user.id)

    db.add(Account(auth_user_id=user.id, name="Eva", language="es", agent_mode=AgentMode.PLATFORM))
    db.flush()


def test_the_signed_in_user_cannot_create_an_account_for_another_user(db: Session) -> None:
    eva, other = AuthUser(email="eva@example.com"), AuthUser(email="otro@example.com")
    db.add_all([eva, other])
    db.flush()
    as_role(db, PLATFORM_ROLE)
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
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    with pytest.raises(IntegrityError, match="cannot change its id or auth user"):
        db.execute(update(Account).where(Account.id == ana.id).values({column: new_value}))


def test_setting_the_account_ends_the_sign_in_lookup(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    as_role(db, PLATFORM_ROLE)
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
        as_role(db, role)
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
    as_role(db, PLATFORM_ROLE)
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


def test_agent_cannot_write_platform_storage_or_billing(db: Session) -> None:
    tables = _tables(db, ("auth", "platform", "storage", "billing", "operations"))
    assert tables, "no tables to check: is the database migrated?"
    for table in tables:
        for privilege in ("INSERT", "UPDATE", "DELETE", "TRUNCATE"):
            assert not has_privilege(db, AGENT_ROLE, table, privilege), (table, privilege)


def test_agent_write_is_refused_by_the_database(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    as_role(db, AGENT_ROLE)
    set_current_account(db, ana.id)

    with pytest.raises(ProgrammingError, match="permission denied"):
        db.execute(update(Account).where(Account.id == ana.id).values(name="changed"))


def test_agent_reads_only_users_and_sessions_in_auth(db: Session) -> None:
    tables = _tables(db, ("auth",))
    assert set(AGENT_AUTH_TABLES) <= set(tables)
    for table in tables:
        expected = table in AGENT_AUTH_TABLES
        assert has_privilege(db, AGENT_ROLE, table, "SELECT") == expected, table


def test_a_new_auth_table_is_not_readable_by_the_agent(db: Session) -> None:
    as_role(db, MIGRATOR_ROLE)
    db.execute(text("CREATE TABLE auth.privileges_probe (id int)"))
    db.execute(text("RESET ROLE"))

    assert has_privilege(db, PLATFORM_ROLE, "auth.privileges_probe", "INSERT")
    assert not has_privilege(db, AGENT_ROLE, "auth.privileges_probe", "SELECT")


def test_a_new_function_is_executable_only_once_granted(db: Session) -> None:
    as_role(db, MIGRATOR_ROLE)
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


def test_agent_has_no_access_to_storage_or_operations(db: Session) -> None:
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
    as_role(db, MIGRATOR_ROLE)
    db.execute(text("CREATE TABLE platform.privileges_probe (id int)"))
    db.execute(text("CREATE TABLE agent.privileges_probe (id int)"))
    db.execute(text("RESET ROLE"))

    assert has_privilege(db, PLATFORM_ROLE, "platform.privileges_probe", "INSERT")
    assert has_privilege(db, AGENT_ROLE, "platform.privileges_probe", "SELECT")
    assert not has_privilege(db, AGENT_ROLE, "platform.privileges_probe", "INSERT")
    assert has_privilege(db, AGENT_ROLE, "agent.privileges_probe", "INSERT")
    assert has_privilege(db, PLATFORM_ROLE, "agent.privileges_probe", "SELECT")
    assert not has_privilege(db, PLATFORM_ROLE, "agent.privileges_probe", "INSERT")


# Row-level security of workspaces and their tables (migration 0012)

# Every table with a workspace_id. test_every_workspace_table_is_tested fails if one is missing,
# so a new table cannot skip these scenarios.
WORKSPACE_TABLES = (
    "platform.folders",
    "platform.documents",
    "platform.document_revisions",
    "platform.revision_images",
    "platform.document_versions",
    "platform.share_links",
    "storage.objects",
    "storage.uploads",
    "storage.saves",
    "storage.workspace_quotas",
    "storage.byte_reservations",
    "agent.conversations",
    "agent.runs",
)
# Also have a workspace_id but follow other rules, tested in tests/test_agent_security.py:
# anyone may add an audit entry, and it may have no workspace.
WORKSPACE_TABLES_TESTED_ELSEWHERE = ("operations.audit_log",)
# Schemas whose tables all hold account data. auth has none of it: it is read before the account
# is known (sign-in, the session cookie).
ACCOUNT_DATA_SCHEMAS = ("platform", "storage", "billing", "agent", "operations")
# Tables in those schemas with no account data, so with no policy:
TABLES_WITHOUT_ACCOUNT_DATA = (
    "agent.rates",  # provider prices, the same for every account
    "operations.backup_runs",  # one row per global backup
    "billing.plans",  # catalog shared by all accounts
    "billing.plan_entitlements",  # versioned catalog limits
    "billing.credit_packs",  # global product catalog
    "billing.gateway_events",  # platform-only inbox, before an account is known
)


def _roles_that_read(table: str) -> list[str]:
    # The agent reads platform but has no access to storage (tested above).
    if table.startswith("storage."):
        return [PLATFORM_ROLE, MIGRATOR_ROLE]
    return [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE]


def _roles_that_write(table: str) -> list[str]:
    # The agent writes its own schema; the platform only reads it.
    if table.startswith("agent."):
        return [AGENT_ROLE, MIGRATOR_ROLE]
    return [PLATFORM_ROLE, MIGRATOR_ROLE]


TABLE_ROLE_CASES = [(table, role) for table in WORKSPACE_TABLES for role in _roles_that_read(table)]
TABLE_WRITE_CASES = [
    (table, role) for table in WORKSPACE_TABLES for role in _roles_that_write(table)
]
WRITE_ROLES = [PLATFORM_ROLE, MIGRATOR_ROLE]


def _fill_workspace(db: Session, account: Account) -> uuid.UUID:
    """A workspace with one row in every table of WORKSPACE_TABLES. Returns its id."""
    workspace = make_workspace(db, account)
    db.add(Folder(workspace_id=workspace.id, name="Clients"))
    document = make_document(db, workspace)
    image = make_object(db, workspace, ObjectKind.IMAGE)
    make_revision(db, document, make_object(db, workspace))
    db.add(
        RevisionImage(
            workspace_id=workspace.id,
            document_id=document.id,
            revision=1,
            editor_hash="img-1",
            image_object_id=image.id,
        )
    )
    db.add(
        DocumentVersion(
            workspace_id=workspace.id,
            document_id=document.id,
            revision=1,
            source=VersionSource.MANUAL,
        )
    )
    make_share_link(db, document, token=str(workspace.id))
    make_save(db, document)
    make_quota(db, workspace)
    db.add(
        ByteReservation(
            workspace_id=workspace.id,
            upload_id=make_upload(db, workspace).id,
            amount=10,
            status=ByteReservationStatus.RESERVED,
            expires_at=in_one_hour(),
        )
    )
    make_run(db, make_conversation(db, document))
    return workspace.id


@pytest.fixture
def two_workspaces(
    db: Session, two_accounts: tuple[Account, Account]
) -> tuple[uuid.UUID, uuid.UUID]:
    """The ids of Ana's and Luis's workspaces, each with a row in every workspace table."""
    ana, luis = two_accounts
    return _fill_workspace(db, ana), _fill_workspace(db, luis)


def _workspace_owner(db: Session, workspace_id: uuid.UUID) -> uuid.UUID:
    owner = db.scalar(select(Workspace.owner_id).where(Workspace.id == workspace_id))
    assert owner is not None
    return owner


def _act_for_ana(
    db: Session, workspaces: tuple[uuid.UUID, uuid.UUID], role: str
) -> tuple[uuid.UUID, uuid.UUID]:
    """Switch to `role` acting for Ana. Her id is read first, as the superuser."""
    ana_workspace, luis_workspace = workspaces
    ana_id = _workspace_owner(db, ana_workspace)
    as_role(db, role)
    set_current_account(db, ana_id)
    return ana_workspace, luis_workspace


def _visible_workspace_ids(db: Session, table: str) -> set[uuid.UUID]:
    # `table` comes from WORKSPACE_TABLES, a constant of this file.
    return set(db.scalars(text(f"SELECT DISTINCT workspace_id FROM {table}")))


@pytest.mark.parametrize("role", [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE])
def test_each_account_sees_only_its_own_workspaces(
    db: Session, two_workspaces: tuple[uuid.UUID, uuid.UUID], role: str
) -> None:
    ana_workspace, _ = _act_for_ana(db, two_workspaces, role)
    assert set(db.scalars(select(Workspace.id))) == {ana_workspace}


@pytest.mark.parametrize(("table", "role"), TABLE_ROLE_CASES)
def test_each_account_sees_only_its_workspace_rows(
    db: Session, two_workspaces: tuple[uuid.UUID, uuid.UUID], table: str, role: str
) -> None:
    ana_workspace, _ = _act_for_ana(db, two_workspaces, role)
    assert _visible_workspace_ids(db, table) == {ana_workspace}


@pytest.mark.parametrize("table", ("platform.workspaces", *WORKSPACE_TABLES))
def test_without_an_account_no_workspace_rows_are_visible(
    db: Session, two_workspaces: tuple[uuid.UUID, uuid.UUID], table: str
) -> None:
    as_role(db, PLATFORM_ROLE)
    assert db.scalar(text(f"SELECT count(*) FROM {table}")) == 0


@pytest.mark.parametrize(("table", "role"), TABLE_WRITE_CASES)
def test_an_account_cannot_change_or_delete_another_workspace_rows(
    db: Session, two_workspaces: tuple[uuid.UUID, uuid.UUID], table: str, role: str
) -> None:
    _, luis_workspace = _act_for_ana(db, two_workspaces, role)
    where = {"luis": luis_workspace}

    updated = db.execute(
        text(f"UPDATE {table} SET workspace_id = workspace_id WHERE workspace_id = :luis"), where
    )
    deleted = db.execute(text(f"DELETE FROM {table} WHERE workspace_id = :luis"), where)

    assert updated.rowcount == 0
    assert deleted.rowcount == 0


@pytest.mark.parametrize(("table", "role"), TABLE_WRITE_CASES)
def test_a_row_cannot_be_moved_to_another_account_workspace(
    db: Session, two_workspaces: tuple[uuid.UUID, uuid.UUID], table: str, role: str
) -> None:
    ana_workspace, luis_workspace = _act_for_ana(db, two_workspaces, role)

    with pytest.raises(ProgrammingError, match="row-level security policy"):
        db.execute(
            text(f"UPDATE {table} SET workspace_id = :luis WHERE workspace_id = :ana"),
            {"luis": luis_workspace, "ana": ana_workspace},
        )


@pytest.mark.parametrize("role", WRITE_ROLES)
def test_a_workspace_cannot_be_given_to_another_account(
    db: Session, two_workspaces: tuple[uuid.UUID, uuid.UUID], role: str
) -> None:
    ana_workspace, luis_workspace = two_workspaces
    luis_id = _workspace_owner(db, luis_workspace)
    _act_for_ana(db, two_workspaces, role)

    with pytest.raises(ProgrammingError, match="row-level security policy"):
        db.execute(update(Workspace).where(Workspace.id == ana_workspace).values(owner_id=luis_id))


def test_an_account_cannot_create_a_workspace_for_another(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, luis = two_accounts
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    db.add(Workspace(owner_id=luis.id, name="Not mine", type=WorkspaceType.PERSONAL))
    with pytest.raises(ProgrammingError, match="row-level security policy"):
        db.flush()


def test_an_account_can_fill_its_own_new_workspace(
    db: Session, two_accounts: tuple[Account, Account]
) -> None:
    ana, _ = two_accounts
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    workspace = Workspace(owner_id=ana.id, name="Personal", type=WorkspaceType.PERSONAL)
    db.add(workspace)
    db.flush()
    db.add(Folder(workspace_id=workspace.id, name="Clients"))
    db.flush()

    assert set(db.scalars(select(Folder.workspace_id))) == {workspace.id}


# Columns that record which account acted. The policy also checks them on write, so a row in
# Ana's workspace cannot claim that Luis did it. test_every_account_column_is_tested keeps
# this list complete.
ACTOR_COLUMNS = {
    "platform.document_revisions": "author_account_id",
    "storage.uploads": "account_id",
    "storage.saves": "account_id",
}


# Columns that say which account a row belongs to (not who acted).
OWNER_COLUMNS = {
    ("platform.workspaces", "owner_id"),
    ("agent.conversations", "account_id"),
    ("agent.period_quotas", "account_id"),
    ("billing.subscriptions", "account_id"),
    ("billing.credit_balances", "account_id"),
    ("billing.credit_movements", "account_id"),
    ("billing.credit_reservations", "account_id"),
}


def _record_action(
    db: Session, table: str, workspace: Workspace, actor_id: uuid.UUID | None
) -> None:
    """Writes one row of `table` in `workspace`, recorded as done by `actor_id`."""
    document = make_document(db, workspace)
    if table == "platform.document_revisions":
        make_revision(db, document, make_object(db, workspace), author_account_id=actor_id)
    elif table == "storage.uploads":
        make_upload(db, workspace, account_id=actor_id)
    else:
        make_save(db, document, account_id=actor_id)


@pytest.mark.parametrize("role", WRITE_ROLES)
@pytest.mark.parametrize("table", ACTOR_COLUMNS)
def test_an_action_cannot_be_recorded_in_another_account_name(
    db: Session, two_accounts: tuple[Account, Account], table: str, role: str
) -> None:
    ana, luis = two_accounts
    workspace = make_workspace(db, ana)
    as_role(db, role)
    set_current_account(db, ana.id)

    with pytest.raises(ProgrammingError, match="row-level security policy"):
        _record_action(db, table, workspace, luis.id)


@pytest.mark.parametrize("role", WRITE_ROLES)
@pytest.mark.parametrize("table", ACTOR_COLUMNS)
def test_an_action_cannot_be_handed_to_another_account(
    db: Session, two_accounts: tuple[Account, Account], table: str, role: str
) -> None:
    ana, luis = two_accounts
    workspace = make_workspace(db, ana)
    _record_action(db, table, workspace, ana.id)
    as_role(db, role)
    set_current_account(db, ana.id)

    with pytest.raises(ProgrammingError, match="row-level security policy"):
        db.execute(
            # `table` and the column come from ACTOR_COLUMNS, constants of this file.
            text(f"UPDATE {table} SET {ACTOR_COLUMNS[table]} = :luis WHERE workspace_id = :ws"),
            {"luis": luis.id, "ws": workspace.id},
        )


@pytest.mark.parametrize("table", ACTOR_COLUMNS)
def test_an_account_records_actions_in_its_own_name(
    db: Session, two_accounts: tuple[Account, Account], table: str
) -> None:
    ana, _ = two_accounts
    workspace = make_workspace(db, ana)
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    _record_action(db, table, workspace, ana.id)

    actors = db.scalars(text(f"SELECT {ACTOR_COLUMNS[table]} FROM {table}")).all()
    assert actors == [ana.id]


def test_a_revision_can_have_no_author(db: Session, two_accounts: tuple[Account, Account]) -> None:
    # An anonymized account leaves its revisions without author (§IX-C).
    ana, _ = two_accounts
    workspace = make_workspace(db, ana)
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, ana.id)

    _record_action(db, "platform.document_revisions", workspace, None)

    assert db.scalar(select(func.count()).select_from(DocumentRevision)) == 1


def test_every_account_column_is_tested(db: Session) -> None:
    # A new column pointing to an account must say who may write it. The owner columns are
    # covered by the isolation tests: workspaces above, conversations here and period quotas in
    # tests/test_agent_security.py, and billing in tests/test_billing_security.py.
    account_columns = db.execute(
        text(
            "SELECT c.conrelid::regclass::text, a.attname FROM pg_constraint c"
            " JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)"
            " JOIN pg_namespace n ON n.oid = c.connamespace"
            " WHERE c.contype = 'f' AND c.confrelid = 'platform.accounts'::regclass"
            " AND n.nspname = ANY(:schemas)"
        ),
        {"schemas": list(ACCOUNT_DATA_SCHEMAS)},
    ).all()
    assert set(map(tuple, account_columns)) - OWNER_COLUMNS == set(ACTOR_COLUMNS.items())


@pytest.mark.parametrize(
    "table", [table for table in WORKSPACE_TABLES if table.startswith("storage.")]
)
def test_agent_reading_storage_gets_permission_denied(db: Session, table: str) -> None:
    # An empty result could also be RLS hiding rows; the agent must be refused outright.
    as_role(db, AGENT_ROLE)
    with pytest.raises(ProgrammingError, match="permission denied for schema storage"):
        db.execute(text(f"SELECT 1 FROM {table} LIMIT 1"))


@pytest.mark.parametrize(("table", "role"), TABLE_WRITE_CASES)
def test_an_account_cannot_insert_rows_into_another_workspace(
    db: Session, two_workspaces: tuple[uuid.UUID, uuid.UUID], table: str, role: str
) -> None:
    ana_workspace, luis_workspace = two_workspaces
    # A copy of one of Ana's rows, pointed at Luis's workspace. Read as the superuser first.
    # PostgreSQL checks the policy before unique keys and CHECKs, so the copy needs no new ids.
    row = db.scalar(
        text(f"SELECT to_jsonb(t) FROM {table} t WHERE workspace_id = :ana LIMIT 1"),
        {"ana": ana_workspace},
    )
    assert row is not None
    row["workspace_id"] = str(luis_workspace)
    _act_for_ana(db, two_workspaces, role)

    with pytest.raises(ProgrammingError, match="row-level security policy"):
        db.execute(
            text(
                f"INSERT INTO {table}"
                f" SELECT * FROM jsonb_populate_record(NULL::{table}, CAST(:row AS jsonb))"
            ),
            {"row": json.dumps(row)},
        )


def test_every_table_with_account_data_has_forced_rls(db: Session) -> None:
    unprotected = db.scalars(
        text(
            "SELECT n.nspname || '.' || c.relname FROM pg_class c"
            " JOIN pg_namespace n ON n.oid = c.relnamespace"
            " WHERE c.relkind IN ('r', 'p') AND n.nspname = ANY(:schemas)"
            " AND NOT (c.relrowsecurity AND c.relforcerowsecurity"
            "          AND EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid = c.oid))"
        ),
        {"schemas": list(ACCOUNT_DATA_SCHEMAS)},
    ).all()
    assert set(unprotected) - set(TABLES_WITHOUT_ACCOUNT_DATA) == set()


def test_every_workspace_table_is_tested(db: Session) -> None:
    with_workspace_id = db.scalars(
        text(
            "SELECT table_schema || '.' || table_name FROM information_schema.columns"
            " WHERE column_name = 'workspace_id' AND table_schema = ANY(:schemas)"
        ),
        {"schemas": list(ACCOUNT_DATA_SCHEMAS)},
    ).all()
    assert set(with_workspace_id) == set(WORKSPACE_TABLES) | set(WORKSPACE_TABLES_TESTED_ELSEWHERE)


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
