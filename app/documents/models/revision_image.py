import uuid

from sqlalchemy import BigInteger, ForeignKeyConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema


class RevisionImage(Base):
    """Which image file each image of a revision uses.

    The editor names images by their content hash (`editor_hash`); this maps that name to the
    stored file. One image file can be used by many revisions (many-to-many).
    """

    __tablename__ = "revision_images"
    __table_args__ = (
        ForeignKeyConstraint(
            ["workspace_id", "document_id", "revision"],
            [
                "platform.document_revisions.workspace_id",
                "platform.document_revisions.document_id",
                "platform.document_revisions.revision",
            ],
            # The generated name would pass PostgreSQL's 63-character limit.
            name="fk_revision_images_revision_document_revisions",
        ),
        ForeignKeyConstraint(
            ["workspace_id", "image_object_id"],
            ["storage.objects.workspace_id", "storage.objects.id"],
        ),
        # Find the revisions that still use a file before deleting it.
        Index(None, "workspace_id", "image_object_id"),
        {"schema": DbSchema.PLATFORM},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    editor_hash: Mapped[str] = mapped_column(primary_key=True)
    workspace_id: Mapped[uuid.UUID]
    image_object_id: Mapped[uuid.UUID]
