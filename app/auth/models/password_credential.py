import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps


class PasswordCredential(Timestamps, Base):
    """The password of a user who signs in with email and password. Optional.

    Kept apart from `users` so the agent's database role can read users without ever
    seeing password hashes (roles in VEC-30).

    Only an Argon2id hash is stored, in PHC format (`$argon2id$v=19$m=...$salt$hash`): it carries
    its own salt and cost, so the cost can be raised later and old hashes still verify.
    """

    __tablename__ = "password_credentials"
    __table_args__ = (
        CheckConstraint("starts_with(password_hash, '$argon2id$')", name="password_hash_argon2id"),
        CheckConstraint("failed_attempts >= 0", name="failed_attempts_non_negative"),
        {"schema": DbSchema.AUTH},
    )

    # Purely dependent on the user, so it is removed with it (Modelo relacional §IX-C).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), primary_key=True
    )
    password_hash: Mapped[str]
    # Wrong passwords in a row. After too many, sign-in is blocked until `locked_until`,
    # which stops password guessing. Reset to 0 on a correct password.
    failed_attempts: Mapped[int] = mapped_column(server_default=text("0"))
    locked_until: Mapped[datetime | None]
