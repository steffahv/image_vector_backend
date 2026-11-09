import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.models.tokens import TOKEN_HASH_CHECK
from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, sha256_check


class AuthSession(UUIDPrimaryKey, Timestamps, Base):
    """A signed-in session. The cookie holds the token; the database only its SHA-256 hash.

    The session is renewed while it is used (see `last_used_at`), and each renewal replaces the
    token (rotation). Look sessions up with the SQL function `auth.find_session()` (migration 0011),
    which the agent uses too, rather than by `token_hash` alone.
    """

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint(TOKEN_HASH_CHECK, name="token_hash_sha256"),
        CheckConstraint(sha256_check("previous_token_hash"), name="previous_token_hash_sha256"),
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
    # The token replaced by the last rotation. Still accepted for a short grace period after
    # `rotated_at`, for requests already on their way; used after that, it means the cookie was
    # copied, and the session is ended. Indexed: every reuse check searches by it.
    previous_token_hash: Mapped[bytes | None] = mapped_column(index=True)
    rotated_at: Mapped[datetime | None]
