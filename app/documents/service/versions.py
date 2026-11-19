"""Restoring a version (VEC-42): publish its revision again as the next revision.

The revision number always goes up: restoring revision 3 while 7 is current makes revision 8, a
copy of 3. The revision that was current is kept as a `restore` version, so the restore can be
undone by restoring that one.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import DocumentVersion, VersionSource
from app.documents.schemas import VersionRestoreResponse
from app.documents.service.access import lock_document, lock_quota, own_document_workspace
from app.documents.service.revisions import publish_revision, revision_files
from app.storage import service as storage


class VersionNotFound(Exception):
    pass


@dataclass
class RestoreConflict(Exception):
    """Another revision was saved since the one on the editor's screen."""

    current_revision: int


class VersionUnavailable(Exception):
    """A file of the version is gone, so it cannot be restored."""


def restore_version(
    db: Session,
    account_id: uuid.UUID,
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    base_revision: int,
) -> VersionRestoreResponse:
    workspace_id = own_document_workspace(db, account_id, document_id)
    lock_quota(db, workspace_id)
    document = lock_document(db, workspace_id, document_id)
    version = db.scalar(
        select(DocumentVersion).where(
            DocumentVersion.id == version_id,
            DocumentVersion.workspace_id == workspace_id,
            DocumentVersion.document_id == document_id,
        )
    )
    if version is None:
        raise VersionNotFound(str(version_id))
    current = document.current_revision
    if current is None or base_revision != current:
        raise RestoreConflict(current or 0)

    undo = DocumentVersion(
        workspace_id=workspace_id,
        document_id=document_id,
        revision=current,
        source=VersionSource.RESTORE,
        label=None,
    )
    db.add(undo)
    files = revision_files(db, workspace_id, document_id, version.revision)
    try:
        revision = publish_revision(db, document, files, account_id)
    except storage.ObjectUnavailable:
        raise VersionUnavailable(str(version_id)) from None
    response = VersionRestoreResponse(revision=revision, undo_version_id=undo.id)
    db.commit()
    return response
