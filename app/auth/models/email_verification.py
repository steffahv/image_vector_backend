from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.models.tokens import TOKEN_HASH_CHECK
from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class VerificationPurpose(StrEnum):
    """What a one-time email link is for."""

    SIGN_IN = "sign_in"  # Sign in without a password.
    VERIFY_EMAIL = "verify_email"  # Confirm the address after signing up with a password.
    PASSWORD_RESET = "password_reset"  # Set a new password.


class EmailVerification(UUIDPrimaryKey, Timestamps, Base):
    """A one-time email link: sign in, verify the address or reset the password.

    No FK to users: for sign-in links the email may not be registered yet.
    """

    __tablename__ = "verifications"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint(TOKEN_HASH_CHECK, name="token_hash_sha256"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        {"schema": DbSchema.AUTH},
    )

    email: Mapped[str] = mapped_column(index=True)
    purpose: Mapped[VerificationPurpose] = mapped_column(text_enum(VerificationPurpose, "purpose"))
    token_hash: Mapped[bytes]
    # Indexed so the cleanup job finds expired links without scanning the table.
    expires_at: Mapped[datetime] = mapped_column(index=True)
    used_at: Mapped[datetime | None]
