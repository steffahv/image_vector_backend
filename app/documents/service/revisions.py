"""Publishing a revision and reading which files a revision uses.

A save (VEC-31) and a restore (VEC-42) both end the same way: a new revision, numbered one past
the current one, becomes the document's head. The number only goes up, so a restore never brings
an old number back.
"""

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import (
    Document,
    DocumentRevision,
    DocumentStatus,
    RevisionAuthorType,
    RevisionImage,
)
from app.storage import service as storage


@dataclass(frozen=True)
class RevisionFiles:
    """The stored files of a revision and how the document JSON names its images."""

    json_object_id: uuid.UUID
    thumbnail_object_id: uuid.UUID | None
    format_version: int
    original_json_bytes: int
    # editor_hash -> stored image
    images: dict[str, uuid.UUID] = field(default_factory=dict)

    @property
    def object_ids(self) -> set[uuid.UUID]:
        ids = {self.json_object_id, *self.images.values()}
        if self.thumbnail_object_id is not None:
            ids.add(self.thumbnail_object_id)
        return ids


def publish_revision(
    db: Session, document: Document, files: RevisionFiles, account_id: uuid.UUID
) -> int:
    """Make `files` the document's next revision and return its number.

    The caller holds the quota and document locks (in that order) and has checked the base
    revision. The files are locked here, last, and must all still be ready; otherwise
    `storage.ObjectUnavailable` is raised before anything is written.
    """
    locked = storage.lock_ready_objects(db, document.workspace_id, files.object_ids)
    revision = (document.current_revision or 0) + 1
    db.add(
        DocumentRevision(
            document_id=document.id,
            revision=revision,
            workspace_id=document.workspace_id,
            json_object_id=files.json_object_id,
            thumbnail_object_id=files.thumbnail_object_id,
            format_version=files.format_version,
            original_json_bytes=files.original_json_bytes,
            author_account_id=account_id,
            author_type=RevisionAuthorType.ACCOUNT,
        )
    )
    db.add_all(
        RevisionImage(
            document_id=document.id,
            revision=revision,
            editor_hash=editor_hash,
            workspace_id=document.workspace_id,
            image_object_id=object_id,
        )
        for editor_hash, object_id in files.images.items()
    )
    document.current_revision = revision
    if document.status == DocumentStatus.DRAFT:
        document.status = DocumentStatus.ACTIVE
    storage.mark_referenced(locked)
    db.flush()
    return revision


def revision_files(
    db: Session, workspace_id: uuid.UUID, document_id: uuid.UUID, revision: int
) -> RevisionFiles:
    saved = db.scalar(
        select(DocumentRevision).where(
            DocumentRevision.workspace_id == workspace_id,
            DocumentRevision.document_id == document_id,
            DocumentRevision.revision == revision,
        )
    )
    if saved is None:
        raise RuntimeError("A document points to a revision that does not exist")
    images = db.execute(
        select(RevisionImage.editor_hash, RevisionImage.image_object_id)
        .where(
            RevisionImage.workspace_id == workspace_id,
            RevisionImage.document_id == document_id,
            RevisionImage.revision == revision,
        )
        .order_by(RevisionImage.editor_hash)
    ).all()
    return RevisionFiles(
        json_object_id=saved.json_object_id,
        thumbnail_object_id=saved.thumbnail_object_id,
        format_version=saved.format_version,
        original_json_bytes=saved.original_json_bytes,
        images={editor_hash: object_id for editor_hash, object_id in images},
    )
