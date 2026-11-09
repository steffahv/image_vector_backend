from datetime import datetime

from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey


class AuthUser(UUIDPrimaryKey, Timestamps, Base):
    """One row per person, identified by email."""

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
