"""SQLAlchemy tables for auth, in the `auth` PostgreSQL schema (VEC-29).

What goes here: who the user is and how they sign in.
- `users` (AuthUser): one row per person, identified by email.
- `accounts` (LinkedAccount): external identity providers linked to a user (Google).
- `sessions` (AuthSession): signed-in sessions. Only the hash of the session token is stored.
- `verifications` (EmailVerification): one-time sign-in links sent by email.

Identity decision (VEC-40): sessions, email links and users are our own code;
Authlib only handles the Google OAuth round trip.
The product account lives in `platform.accounts` (app/documents/models.py), not here.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum

SHA256_BYTES = 32


class IdentityProvider(StrEnum):
    GOOGLE = "google"


class VerificationPurpose(StrEnum):
    SIGN_IN = "sign_in"


class AuthUser(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "users"
    __table_args__ = (
        UniqueConstraint("email"),
        # Stored lowercased so the same address cannot sign up twice with different casing.
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        {"schema": DbSchema.AUTH},
    )

    email: Mapped[str]
    email_verified_at: Mapped[datetime | None]
    name: Mapped[str | None]
    image_url: Mapped[str | None]


class LinkedAccount(UUIDPrimaryKey, Timestamps, Base):
    """An external identity linked to a user.

    Provider tokens are not stored: the provider is only used to sign in.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id"),
        {"schema": DbSchema.AUTH},
    )

    # Purely dependent on the user, so it is removed with it (Modelo relacional §IX-C).
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), index=True
    )
    provider: Mapped[IdentityProvider] = mapped_column(text_enum(IdentityProvider, "provider"))
    # The provider's stable user id (Google's `sub`), never the email.
    provider_account_id: Mapped[str]


class AuthSession(UUIDPrimaryKey, Timestamps, Base):
    """A signed-in session. The cookie holds the token; the database only its SHA-256 hash."""

    __tablename__ = "sessions"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint(f"octet_length(token_hash) = {SHA256_BYTES}", name="token_hash_sha256"),
        {"schema": DbSchema.AUTH},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("auth.users.id", ondelete="CASCADE"), index=True
    )
    token_hash: Mapped[bytes]
    expires_at: Mapped[datetime] = mapped_column(index=True)
    user_agent: Mapped[str | None]


class EmailVerification(UUIDPrimaryKey, Timestamps, Base):
    """A one-time sign-in link. No FK to users: the email may not be registered yet."""

    __tablename__ = "verifications"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        CheckConstraint(f"octet_length(token_hash) = {SHA256_BYTES}", name="token_hash_sha256"),
        CheckConstraint("email = lower(email)", name="email_lowercase"),
        {"schema": DbSchema.AUTH},
    )

    email: Mapped[str] = mapped_column(index=True)
    purpose: Mapped[VerificationPurpose] = mapped_column(text_enum(VerificationPurpose, "purpose"))
    token_hash: Mapped[bytes]
    expires_at: Mapped[datetime]
    used_at: Mapped[datetime | None]
