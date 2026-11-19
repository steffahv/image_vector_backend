from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.auth.models import AuthUser
from app.core.db import engine
from app.documents.models import Account, AgentMode

if TYPE_CHECKING:
    from tests.document_api import Api


@pytest.fixture
def api(db: Session) -> Iterator["Api"]:
    """Ana signed in, with a workspace, space and a draft document (tests/document_api.py)."""
    from tests.document_api import signed_in_api

    yield from signed_in_api(db)


@pytest.fixture
def db() -> Iterator[Session]:
    """A session inside a transaction that is rolled back after the test.

    Needs a database migrated to head (`alembic upgrade head`). Nothing is left behind.
    """
    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, join_transaction_mode="create_savepoint")
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()


def as_role(db: Session, role: str) -> None:
    """Act as a database role until the test transaction ends.

    Tests connect as a superuser, which skips row-level security; switching role makes the
    policies apply as they do for the service. `role` is one of the role constants in app.core.db.
    """
    db.execute(text(f"SET LOCAL ROLE {role}"))


def has_privilege(db: Session, role: str, table: str, privilege: str) -> bool:
    return bool(db.scalar(select(func.has_table_privilege(role, table, privilege))))


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


@pytest.fixture
def two_accounts(db: Session) -> tuple[Account, Account]:
    """Two accounts created as the test user, before switching to a restricted role."""
    return _account(db, "ana@example.com"), _account(db, "luis@example.com")
