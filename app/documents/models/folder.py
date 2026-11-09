import uuid

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey


class Folder(UUIDPrimaryKey, Timestamps, Base):
    """A folder in a workspace. Its parent, if any, is in the same workspace.

    The database blocks a folder being its own parent. Longer cycles (A → B → A) are
    checked by the service that moves folders, because a CHECK cannot follow the tree.
    """

    __tablename__ = "folders"
    __table_args__ = (
        # Lets other tables point to (workspace_id, id) and stay in the same workspace.
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "parent_id"],
            ["platform.folders.workspace_id", "platform.folders.id"],
        ),
        CheckConstraint("parent_id <> id", name="not_own_parent"),
        Index(None, "workspace_id", "parent_id"),
        {"schema": DbSchema.PLATFORM},
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.workspaces.id"))
    parent_id: Mapped[uuid.UUID | None]
    name: Mapped[str]
