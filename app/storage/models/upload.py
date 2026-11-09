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

from app.core.model_base import (
    Base,
    CreatedAt,
    DbSchema,
    UUIDPrimaryKey,
    sha256_check,
    text_enum,
)
from app.storage.models.stored_object import ObjectKind


class UploadStatus(StrEnum):
    """Lifecycle of an upload (Modelo relacional §X, `subidas.estado`)."""

    PENDING = "pending"
    VERIFYING = "verifying"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    EXPIRED = "expired"


class Upload(UUIDPrimaryKey, CreatedAt, Base):
    """One attempt to upload a file straight to storage with a signed URL.

    The browser writes to `temp_key`; once the bytes are verified, the upload points to the
    final stored object. A deduplicated image can be the result of several uploads.
    """

    __tablename__ = "uploads"
    __table_args__ = (
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("temp_key"),
        ForeignKeyConstraint(
            ["workspace_id", "save_id"],
            ["storage.saves.workspace_id", "storage.saves.id"],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "object_id"],
            ["storage.objects.workspace_id", "storage.objects.id"],
        ),
        CheckConstraint("max_bytes > 0", name="max_bytes_positive"),
        CheckConstraint(sha256_check("declared_sha256"), name="declared_sha256_length"),
        Index(None, "workspace_id", "save_id"),
        Index(None, "workspace_id", "object_id"),
        # Cleanup job: find expired uploads by status and deadline.
        Index(None, "status", "expires_at"),
        {"schema": DbSchema.STORAGE},
    )

    workspace_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"), index=True)
    save_id: Mapped[uuid.UUID | None]
    kind: Mapped[ObjectKind] = mapped_column(text_enum(ObjectKind, "kind"))
    temp_key: Mapped[str]
    max_bytes: Mapped[int] = mapped_column(BigInteger)
    declared_sha256: Mapped[bytes | None]
    status: Mapped[UploadStatus] = mapped_column(text_enum(UploadStatus, "status"))
    object_id: Mapped[uuid.UUID | None]
    expires_at: Mapped[datetime]
    lease_until: Mapped[datetime | None]
    error_code: Mapped[str | None]
