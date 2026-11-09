from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.core.db import engine


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
