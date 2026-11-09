import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class IdentityProvider(StrEnum):
    GOOGLE = "google"


class LinkedAccount(UUIDPrimaryKey, Timestamps, Base):
    """An external identity linked to a user.

    Provider tokens are not stored: the provider is only used to sign in.
    """

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("provider", "provider_account_id"),
        # One account per provider and person: a user cannot link two Google accounts.
        # Starts with user_id, so it also serves lookups by user.
        UniqueConstraint("user_id", "provider"),
        {"schema": DbSchema.AUTH},
    )

    # Purely dependent on the user, so it is removed with it (Modelo relacional §IX-C).
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("auth.users.id", ondelete="CASCADE"))
    provider: Mapped[IdentityProvider] = mapped_column(text_enum(IdentityProvider, "provider"))
    # The provider's stable user id (Google's `sub`), never the email.
    provider_account_id: Mapped[str]
