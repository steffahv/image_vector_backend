"""Database connection and the identity of the connected account.

What goes here:
- The SQLAlchemy engine and the session factory.
- `get_db()`, the FastAPI dependency that opens one session per request.
- `set_current_account()`, which tells PostgreSQL which account the session acts for, so the
  row-level security policies filter every query by it.
- `set_current_user()`, which tells PostgreSQL which auth user is signed in, so sign-in can find
  (or create) that user's account before knowing its id.
- The names of the database roles (created by migration 0010).

What does not go here: the model base and mixins (core/model_base.py), tables (each module's
models/) or queries (each module's service/).
"""

import uuid
from collections.abc import Iterator

from sqlalchemy import Connection, create_engine, event, func, select
from sqlalchemy.orm import Session, SessionTransaction, sessionmaker

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
    for key, setting in _SETTINGS.items():
        value = session.info.get(key)
        if value is not None:
            _set_setting(connection, setting, value)


def _set_identity(db: Session, key: str, value: uuid.UUID | None) -> None:
    db.info[key] = value
    if db.in_transaction():
        _set_setting(db.connection(), _SETTINGS[key], value)


def set_current_account(db: Session, account_id: uuid.UUID | None) -> None:
    """Act for `account_id` from now on in this session; `None` stops acting for any account.

    Without an account, tables with RLS show no rows and accept no writes.
    The auth dependency (VEC-4) calls this once it knows who is signed in.
    """
    _set_identity(db, "account_id", account_id)


def set_current_user(db: Session, auth_user_id: uuid.UUID | None) -> None:
    """Mark `auth_user_id` as signed in for this session; `None` clears it.

    The accounts policy then also shows that user's own account, so sign-in can find it, or
    create it the first time, before it knows the account id. Only `platform.accounts` uses it.
    """
    _set_identity(db, "user_id", auth_user_id)


def get_db() -> Iterator[Session]:
    """One session per request, with no account until `set_current_account()` is called.

    The account is set with SET LOCAL at the start of each transaction (see
    `_apply_identity`), never on the connection, so it cannot leak between requests.
    """
    with SessionLocal() as db:
        yield db
