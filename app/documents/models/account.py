import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class AgentMode(StrEnum):
    """Who pays for the agent's model calls (Modelo relacional §X, `cuentas.modo_agente`)."""

    PLATFORM = "platform"
    OWN_KEY = "own_key"


class Account(UUIDPrimaryKey, Timestamps, Base):
    """The product account. Created the first time a user signs in (VEC-4)."""

    __tablename__ = "accounts"
    __table_args__ = (
        UniqueConstraint("auth_user_id"),
        {"schema": DbSchema.PLATFORM},
    )

    # No cascade: deleting the identity must not silently delete the account's data (§IX-C).
    auth_user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("auth.users.id"))
    name: Mapped[str]
    language: Mapped[str]
    agent_mode: Mapped[AgentMode] = mapped_column(text_enum(AgentMode, "agent_mode"))
    last_access_at: Mapped[datetime | None]
    deletion_requested_at: Mapped[datetime | None]
