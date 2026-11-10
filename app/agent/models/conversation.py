import uuid

from sqlalchemy import ForeignKey, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey


class Conversation(UUIDPrimaryKey, Timestamps, Base):
    """A chat between an account and the agent, optionally about one document."""

    __tablename__ = "conversations"
    __table_args__ = (
        # Lets runs point to (account_id, workspace_id, id): a conversation of that account and
        # workspace, so a run cannot be filed under someone else's conversation.
        UniqueConstraint("account_id", "workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["platform.documents.workspace_id", "platform.documents.id"],
        ),
        Index(None, "workspace_id", "document_id"),
        {"schema": DbSchema.AGENT},
    )

    # No cascade from the account or the workspace (§IX-C).
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"))
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.workspaces.id"))
    document_id: Mapped[uuid.UUID | None]
    title: Mapped[str | None]
