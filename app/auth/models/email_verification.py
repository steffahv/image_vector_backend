from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.auth.models.tokens import TOKEN_HASH_CHECK
from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class VerificationPurpose(StrEnum):
    SIGN_IN = "sign_in"


class EmailVerification(UUIDPrimaryKey, Timestamps, Base):
    """A one-time sign-in link. No FK to users: the email may not be registered yet."""

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
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
