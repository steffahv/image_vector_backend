import uuid
from datetime import datetime
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

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum


class SaveStatus(StrEnum):
    """Lifecycle of a save request (Modelo relacional §X, `guardados.estado`)."""

    PREPARING = "preparing"
    CONFIRMED = "confirmed"
    CONFLICT = "conflict"
    CANCELED = "canceled"
    EXPIRED = "expired"


class DocumentSave(UUIDPrimaryKey, CreatedAt, Base):
    """One request to save a document. Its files arrive as uploads.

    The idempotency key makes a retried request return the same save instead of a second one.
    `base_revision` is the revision the editor started from: if the document moved on in the
    meantime, the save ends in `conflict`.
    """

    __tablename__ = "saves"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("document_id", "idempotency_key"),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["platform.documents.workspace_id", "platform.documents.id"],
        ),
        CheckConstraint("base_revision >= 0", name="base_revision_non_negative"),
        CheckConstraint("result_revision > 0", name="result_revision_positive"),
        # Cleanup job: find expired requests by status and deadline.
        Index(None, "status", "expires_at"),
        {"schema": DbSchema.STORAGE},
    )

    workspace_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"), index=True)
    idempotency_key: Mapped[uuid.UUID]
    request_fingerprint: Mapped[bytes]
    base_revision: Mapped[int] = mapped_column(BigInteger)
    result_revision: Mapped[int | None] = mapped_column(BigInteger)
    status: Mapped[SaveStatus] = mapped_column(text_enum(SaveStatus, "status"))
    expires_at: Mapped[datetime]
