import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum


class VersionSource(StrEnum):
    """Why a version was kept (Modelo relacional §X, `versiones_documento.origen`)."""

    AUTOMATIC = "automatic"
    MANUAL = "manual"
    PRE_AGENT = "pre_agent"
    RESTORE = "restore"


class DocumentVersion(UUIDPrimaryKey, CreatedAt, Base):
    """A mark that keeps one revision in the document history.

    A revision is a saved state; a version says that state must be kept and shown.
    """

    __tablename__ = "document_versions"
    __table_args__ = (
        # Lets agent runs point to (workspace_id, document_id, id): a version of that document.
        UniqueConstraint("workspace_id", "document_id", "id"),
        ForeignKeyConstraint(
            ["workspace_id", "document_id", "revision"],
            [
                "platform.document_revisions.workspace_id",
                "platform.document_revisions.document_id",
                "platform.document_revisions.revision",
            ],
            # The generated name would pass PostgreSQL's 63-character limit.
            name="fk_document_versions_revision_document_revisions",
        ),
        Index(None, "workspace_id", "document_id", "revision"),
        {"schema": DbSchema.PLATFORM},
    )

    workspace_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID]
    revision: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[VersionSource] = mapped_column(text_enum(VersionSource, "source"))
    label: Mapped[str | None]
    protected_until: Mapped[datetime | None]
