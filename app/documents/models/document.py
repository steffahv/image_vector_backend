import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Double,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey, text_enum


class DocumentStatus(StrEnum):
    """Lifecycle of a document (Modelo relacional §X, `documentos.estado`)."""

    DRAFT = "draft"
    ACTIVE = "active"
    TRASH = "trash"


class DocumentSource(StrEnum):
    """How the document was created (Modelo relacional §X, `documentos.origen`)."""

    AGENT = "agent"
    TEMPLATE = "template"
    BLANK = "blank"
    IMPORTED = "imported"


class Document(UUIDPrimaryKey, Timestamps, Base):
    """A design document. Its content lives in revisions; `current_revision` is the latest one."""

    __tablename__ = "documents"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "folder_id"],
            ["platform.folders.workspace_id", "platform.folders.id"],
        ),
        # Checked at commit, so a revision and the document pointing to it can be
        # written in the same transaction. use_alter: documents and revisions point
        # to each other, so this key is added after both tables exist.
        ForeignKeyConstraint(
            ["workspace_id", "id", "current_revision"],
            [
                "platform.document_revisions.workspace_id",
                "platform.document_revisions.document_id",
                "platform.document_revisions.revision",
            ],
            name="fk_documents_current_revision_document_revisions",
            deferrable=True,
            initially="DEFERRED",
            use_alter=True,
        ),
        # 'Infinity' also rejects NaN, which PostgreSQL sorts above every number.
        CheckConstraint(
            "width > 0 AND width < 'Infinity' AND height > 0 AND height < 'Infinity'",
            name="dimensions_positive_finite",
        ),
        CheckConstraint(
            "status = 'draft' OR current_revision IS NOT NULL",
            name="current_revision_required",
        ),
        # Library listing: by workspace, status and last change; and by folder.
        Index(None, "workspace_id", "status", "updated_at"),
        Index(None, "workspace_id", "folder_id"),
        {"schema": DbSchema.PLATFORM},
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.workspaces.id"))
    folder_id: Mapped[uuid.UUID | None]
    name: Mapped[str]
    format: Mapped[str]
    width: Mapped[float] = mapped_column(Double)
    height: Mapped[float] = mapped_column(Double)
    current_revision: Mapped[int | None] = mapped_column(BigInteger)
    source: Mapped[DocumentSource] = mapped_column(text_enum(DocumentSource, "source"))
    status: Mapped[DocumentStatus] = mapped_column(text_enum(DocumentStatus, "status"))
    deleted_at: Mapped[datetime | None]
