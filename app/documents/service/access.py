"""Who may touch a document, and the locks every change to a document takes, in order.

Every change locks the workspace quota first, then the document, then its files: the same order
everywhere, so two changes of one workspace never deadlock.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import Document, DocumentStatus, Workspace
from app.storage import service as storage
from app.storage.models import WorkspaceQuota


class DocumentNotFound(Exception):
    """Not a document of the account (or in the trash). Answered as 404, never 403."""


def own_document_workspace(
    db: Session, account_id: uuid.UUID, document_id: uuid.UUID, *, include_trash: bool = False
) -> uuid.UUID:
    """The document's workspace, checked to be one the account owns. RLS is the second check."""
    query = (
        select(Document.workspace_id)
        .join(Workspace, Workspace.id == Document.workspace_id)
        .where(Document.id == document_id, Workspace.owner_id == account_id)
    )
    if not include_trash:
        query = query.where(Document.status != DocumentStatus.TRASH)
    workspace_id = db.scalar(query)
    if workspace_id is None:
        raise DocumentNotFound(str(document_id))
    return workspace_id


def lock_quota(db: Session, workspace_id: uuid.UUID) -> WorkspaceQuota:
    try:
        return storage.lock_quota(db, workspace_id)
    except storage.QuotaMissing:
        raise storage.InsufficientStorage(str(workspace_id)) from None


def lock_document(db: Session, workspace_id: uuid.UUID, document_id: uuid.UUID) -> Document:
    document = db.scalar(
        select(Document)
        .where(Document.id == document_id, Document.workspace_id == workspace_id)
        .with_for_update()
    )
    if document is None or document.status == DocumentStatus.TRASH:
        raise DocumentNotFound(str(document_id))
    return document
