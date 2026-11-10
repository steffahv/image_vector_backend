import uuid
from enum import StrEnum
from typing import Any

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum


class MessageRole(StrEnum):
    """Who wrote a message."""

    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Message(UUIDPrimaryKey, CreatedAt, Base):
    """One message of a conversation, in the order given by `sequence`. Never changes.

    `content` uses the project's own format, not the AI SDK's, so the history does not depend
    on that library's version.
    """

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "sequence"),
        CheckConstraint("sequence > 0", name="sequence_positive"),
        {"schema": DbSchema.AGENT},
    )

    # Messages exist only as part of their conversation, so they go with it (§IX-C).
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("agent.conversations.id", ondelete="CASCADE")
    )
    sequence: Mapped[int] = mapped_column(BigInteger)
    role: Mapped[MessageRole] = mapped_column(text_enum(MessageRole, "role"))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
