import uuid
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, text_enum


class RevisionAuthorType(StrEnum):
    """Who wrote a revision: a person through the editor or the agent."""

    ACCOUNT = "account"
    AGENT = "agent"


class DocumentRevision(CreatedAt, Base):
    """One saved state of a document. Never changes after insert.

    The JSON content and the thumbnail are files in storage.objects of the same workspace.
    """

    __tablename__ = "document_revisions"
    __table_args__ = (
        # Lets versions, images and documents point to (workspace_id, document_id, revision).
        UniqueConstraint("workspace_id", "document_id", "revision"),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["platform.documents.workspace_id", "platform.documents.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "json_object_id"],
            ["storage.objects.workspace_id", "storage.objects.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "thumbnail_object_id"],
            ["storage.objects.workspace_id", "storage.objects.id"],
        ),
        CheckConstraint("revision > 0", name="revision_positive"),
        CheckConstraint("original_json_bytes >= 0", name="original_json_bytes_non_negative"),
        Index(None, "workspace_id", "json_object_id"),
        Index(None, "workspace_id", "thumbnail_object_id"),
        # Deleting an account sets its revisions' author to NULL; without this index
        # PostgreSQL would scan the whole table, which is the largest one.
        Index(
            None,
            "author_account_id",
            postgresql_where="author_account_id IS NOT NULL",
        ),
        {"schema": DbSchema.PLATFORM},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    workspace_id: Mapped[uuid.UUID]
    json_object_id: Mapped[uuid.UUID]
    thumbnail_object_id: Mapped[uuid.UUID | None]
    format_version: Mapped[int]
    original_json_bytes: Mapped[int] = mapped_column(BigInteger)
    # SET NULL: the author can be anonymized without losing the revision (§IX-C).
    author_account_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform.accounts.id", ondelete="SET NULL")
    )
    author_type: Mapped[RevisionAuthorType] = mapped_column(
        text_enum(RevisionAuthorType, "author_type")
    )
