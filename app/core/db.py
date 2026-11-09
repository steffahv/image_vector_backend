"""Database connection and the identity of the connected account.

What goes here:
- The SQLAlchemy engine and the session factory.
- `get_db()`, the FastAPI dependency that opens one session per request.
- `set_current_account()`, which tells PostgreSQL which account the session acts for, so the
  row-level security policies filter every query by it.
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

_ACCOUNT_ID_KEY = "account_id"

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def _set_account_setting(connection: Connection, account_id: uuid.UUID | None) -> None:
    # set_config(..., true) is SET LOCAL with a bound parameter: it ends with the transaction,
    # so a pooled connection never carries the account into the next request.
    value = "" if account_id is None else str(account_id)
    connection.execute(select(func.set_config(ACCOUNT_ID_SETTING, value, True)))


@event.listens_for(Session, "after_begin")
def _apply_current_account(
    session: Session, transaction: SessionTransaction, connection: Connection
) -> None:
    """Every transaction the session opens starts with its account set, including after a commit."""
    account_id = session.info.get(_ACCOUNT_ID_KEY)
    if account_id is not None:
        _set_account_setting(connection, account_id)


def set_current_account(db: Session, account_id: uuid.UUID | None) -> None:
    """Act for `account_id` from now on in this session; `None` stops acting for any account.

    Without an account, tables with RLS show no rows and accept no writes.
    The auth dependency (VEC-4) calls this once it knows who is signed in.
    """
    db.info[_ACCOUNT_ID_KEY] = account_id
    if db.in_transaction():
        _set_account_setting(db.connection(), account_id)


def get_db() -> Iterator[Session]:
    """One session per request, with no account until `set_current_account()` is called.

    The account is set with SET LOCAL at the start of each transaction (see
    `_apply_current_account`), never on the connection, so it cannot leak between requests.
    """
    with SessionLocal() as db:
        yield db
