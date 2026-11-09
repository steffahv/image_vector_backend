"""Database connection and the identity of the connected account.

What goes here:
- The SQLAlchemy engine and the session factory.
- `get_db()`, the FastAPI dependency that opens one session per request.
- `set_current_account()`, which tells PostgreSQL which account the session acts for, so the
  row-level security policies filter every query by it.
- `set_current_user()`, which tells PostgreSQL which auth user is signed in, so sign-in can find
  (or create) that user's account before knowing its id.
- The names of the database roles (created by migration 0010).
- `check_app_role()`, which stops the app from starting outside development with a database user
  that would skip row-level security.

What does not go here: the model base and mixins (core/model_base.py), tables (each module's
models/) or queries (each module's service/).
"""

import uuid
from collections.abc import Iterator

from sqlalchemy import Connection, create_engine, event, func, select, text
from sqlalchemy.orm import ORMExecuteState, Session, SessionTransaction, sessionmaker

from app.core.config import get_settings

# Database roles. Each environment logs in with its own users, members of these roles.
MIGRATOR_ROLE = "vectoredit_migrator"
PLATFORM_ROLE = "vectoredit_platform"
AGENT_ROLE = "vectoredit_agent"

# PostgreSQL setting read by platform.current_account_id(), which every RLS policy uses.
# The TypeScript agent sets the same one.
ACCOUNT_ID_SETTING = "app.account_id"
# Read by platform.current_auth_user_id(): the accounts policy also shows the signed-in user's
# own account. Only the platform sets it, during sign-in.
USER_ID_SETTING = "app.user_id"

# Session.info key -> PostgreSQL setting it is applied to.
_SETTINGS = {"account_id": ACCOUNT_ID_SETTING, "user_id": USER_ID_SETTING}

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _set_setting(connection: Connection, setting: str, value: uuid.UUID | None) -> None:
    # set_config(..., true) is SET LOCAL with a bound parameter: it ends with the transaction,
    # so a pooled connection never carries the identity into the next request.
    text_value = "" if value is None else str(value)
    connection.execute(select(func.set_config(setting, text_value, True)))


@event.listens_for(Session, "after_begin")
def _apply_identity(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """Every transaction the session opens starts with its identity set, also after a commit."""
    session.info.pop(_STALE_KEY, None)
    for key, setting in _SETTINGS.items():
        value = session.info.get(key)
        if value is not None:
            _set_setting(connection, setting, value)


_STALE_KEY = "identity_stale"


@event.listens_for(Session, "after_transaction_end")
def _mark_identity_stale(session: Session, transaction: SessionTransaction) -> None:
    """A rolled-back savepoint also undoes a SET LOCAL made inside it.

    No SQL can run while the savepoint closes, so this only marks the identity to be set again
    before the next query or flush (see `_reapply_identity`). Without it, a
    `set_current_account()` inside `begin_nested()` would be lost on rollback while
    `session.info` still has it, and the rest of the transaction would see no rows.
    """
    if transaction.nested and any(key in session.info for key in _SETTINGS):
        session.info[_STALE_KEY] = True


def _reapply_identity(session: Session) -> None:
    if session.info.pop(_STALE_KEY, False) and session.in_transaction():
        connection = session.connection()
        for key, setting in _SETTINGS.items():
            _set_setting(connection, setting, session.info.get(key))


@event.listens_for(Session, "do_orm_execute")
def _reapply_before_query(state: ORMExecuteState) -> None:
    _reapply_identity(state.session)


@event.listens_for(Session, "before_flush")
def _reapply_before_flush(session: Session, *_: object) -> None:
    _reapply_identity(session)


def _set_identity(db: Session, key: str, value: uuid.UUID | None) -> None:
    db.info[key] = value
    if db.in_transaction():
        _set_setting(db.connection(), _SETTINGS[key], value)


def set_current_account(db: Session, account_id: uuid.UUID | None) -> None:
    """Act for `account_id` from now on in this session; `None` stops acting for any account.

    Without an account, tables with RLS show no rows and accept no writes.
    The auth dependency (VEC-4) calls this once it knows who is signed in.
    Setting an account also clears the signed-in user from `set_current_user()`: that one is only
    for finding the account during sign-in, and must not keep widening what the session sees.
    """
    if account_id is not None and db.info.get("user_id") is not None:
        _set_identity(db, "user_id", None)
    _set_identity(db, "account_id", account_id)


def set_current_user(db: Session, auth_user_id: uuid.UUID | None) -> None:
    """Mark `auth_user_id` as signed in for this session; `None` clears it.

    The accounts policy then also shows that user's own account, so sign-in can find it, or
    create it the first time, before it knows the account id. Only `platform.accounts` uses it.
    `set_current_account()` clears it once the account is known.
    """
    _set_identity(db, "user_id", auth_user_id)


def check_app_role(connection: Connection) -> None:
    """Refuse to run as a database user that skips row-level security or can change tables.

    A superuser or a BYPASSRLS user skips every policy, and the migrator owns the tables: with any
    of them the app would work normally while no policy protects anything. The app must connect
    as a member of the platform role and nothing more.
    """
    row = connection.execute(
        text(
            "SELECT r.rolname, r.rolsuper, r.rolbypassrls,"
            " pg_has_role(r.oid, :migrator, 'MEMBER') AS is_migrator,"
            " pg_has_role(r.oid, :platform, 'MEMBER') AS is_platform"
            " FROM pg_roles r WHERE r.rolname = current_user"
        ),
        {"migrator": MIGRATOR_ROLE, "platform": PLATFORM_ROLE},
    ).one()
    if row.rolsuper or row.rolbypassrls:
        problem = "is a superuser or has BYPASSRLS, so row-level security does not apply"
    elif row.is_migrator:
        problem = f"is a member of {MIGRATOR_ROLE}, which owns the tables"
    elif not row.is_platform:
        problem = f"is not a member of {PLATFORM_ROLE}"
    else:
        return
    raise RuntimeError(
        f"Database user {row.rolname!r} {problem}. Outside development, DATABASE_URL must be"
        f" a login user of {PLATFORM_ROLE} (see scripts/create_login_roles.sql)."
    )


def get_db() -> Iterator[Session]:
    """One session per request, with no account until `set_current_account()` is called.

    The account is set with SET LOCAL at the start of each transaction (see
    `_apply_identity`), never on the connection, so it cannot leak between requests.
    """
    with SessionLocal() as db:
        yield db
