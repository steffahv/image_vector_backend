import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class WorkspaceType(StrEnum):
    """Kinds of workspace (Modelo relacional §X, `espacios.tipo`). Only personal in the MVP."""

    PERSONAL = "personal"


class Workspace(UUIDPrimaryKey, Timestamps, Base):
    """The space that owns folders, documents and files. Every account has one personal space."""

    __tablename__ = "workspaces"
    __table_args__ = (
        # One personal workspace per account; other types may repeat in the future.
        Index(
            "uq_workspaces_owner_id_personal",
            "owner_id",
            unique=True,
            postgresql_where="type = 'personal'",
        ),
        {"schema": DbSchema.PLATFORM},
    )

    # No cascade: deleting the account must not silently delete its documents (§IX-C).
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"))
    name: Mapped[str]
    type: Mapped[WorkspaceType] = mapped_column(text_enum(WorkspaceType, "type"))
