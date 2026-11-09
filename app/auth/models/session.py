import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.models.tokens import TOKEN_HASH_CHECK
from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey


class AuthSession(UUIDPrimaryKey, Timestamps, Base):
    """A signed-in session. The cookie holds the token; the database only its SHA-256 hash.

    The session is renewed while it is used (see `last_used_at`).
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint(TOKEN_HASH_CHECK, name="token_hash_sha256"),
        {"schema": DbSchema.AUTH},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes]
    expires_at: Mapped[datetime] = mapped_column(index=True)
    # Sliding sessions: each use refreshes it and pushes `expires_at` forward,
    # so an active user is never signed out.
    last_used_at: Mapped[datetime] = mapped_column(server_default=func.now())
    user_agent: Mapped[str | None]
