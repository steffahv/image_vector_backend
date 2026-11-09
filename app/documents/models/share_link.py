import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, sha256_check


class ShareLink(UUIDPrimaryKey, CreatedAt, Base):
    """A public read-only link to a document.

    The URL carries the token; the database only keeps its SHA-256 hash, so a database leak
    does not expose working links.
    """

    __tablename__ = "share_links"
    __table_args__ = (
        UniqueConstraint("token_hash"),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["platform.documents.workspace_id", "platform.documents.id"],
        ),
        CheckConstraint(sha256_check("token_hash"), name="token_hash_sha256"),
        Index(None, "workspace_id", "document_id"),
        {"schema": DbSchema.PLATFORM},
    )

    workspace_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID]
    token_hash: Mapped[bytes]
    active: Mapped[bool]
    allows_download: Mapped[bool]
    expires_at: Mapped[datetime | None]
