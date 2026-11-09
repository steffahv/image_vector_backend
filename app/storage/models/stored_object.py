import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import (
    Base,
    CreatedAt,
    DbSchema,
    UUIDPrimaryKey,
    sha256_check,
    text_enum,
)


class ObjectKind(StrEnum):
    """What a stored file is (Modelo relacional §X, `objetos.clase`)."""

    DOCUMENT_JSON = "document_json"
    IMAGE = "image"
    THUMBNAIL = "thumbnail"
    EXPORT = "export"


class ObjectStatus(StrEnum):
    """Lifecycle of a stored file (Modelo relacional §X, `objetos.estado`)."""

    READY = "ready"
    PENDING_DELETION = "pending_deletion"
    DELETED = "deleted"


class ObjectEncoding(StrEnum):
    """How the bytes are stored (Modelo relacional §X, `objetos.codificacion`)."""

    IDENTITY = "identity"
    GZIP = "gzip"


class StoredObject(UUIDPrimaryKey, CreatedAt, Base):
    """Metadata and location of one file in S3-compatible storage. The bytes are not here."""

    __tablename__ = "objects"
    __table_args__ = (
        # Lets revisions, uploads and exports point to a file of the same workspace.
        UniqueConstraint("workspace_id", "id"),
        UniqueConstraint("bucket", "key"),
        # The same image is stored once per workspace.
        Index(
            "uq_objects_workspace_id_sha256_ready_image",
            "workspace_id",
            "sha256",
            unique=True,
            postgresql_where="kind = 'image' AND status = 'ready'",
        ),
        CheckConstraint(sha256_check("sha256"), name="sha256_length"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        {"schema": DbSchema.STORAGE},
    )

    # No cascade: deleting rows never deletes bytes in storage (§IX-C).
    workspace_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.workspaces.id"))
    kind: Mapped[ObjectKind] = mapped_column(text_enum(ObjectKind, "kind"))
    bucket: Mapped[str]
    key: Mapped[str]
    sha256: Mapped[bytes]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    mime_type: Mapped[str]
    encoding: Mapped[ObjectEncoding] = mapped_column(text_enum(ObjectEncoding, "encoding"))
    width: Mapped[int | None]
    height: Mapped[int | None]
    status: Mapped[ObjectStatus] = mapped_column(text_enum(ObjectStatus, "status"))
    verified_at: Mapped[datetime]
    unreferenced_since: Mapped[datetime | None]
    deleted_at: Mapped[datetime | None]
    copy_verified_at: Mapped[datetime | None]
