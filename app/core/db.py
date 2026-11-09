"""Database connection.

What goes here:
- The SQLAlchemy engine and the session factory.
- `get_db()`, the FastAPI dependency that opens one session per request.

What does not go here: the model base and mixins (core/model_base.py), tables (each module's
models.py) or queries (each module's service.py).
"""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    with SessionLocal() as db:
        yield db
