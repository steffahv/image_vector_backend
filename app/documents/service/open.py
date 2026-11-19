"""Opening a document (Arquitectura §III-B, VEC-42): signed URLs to its files, never the files.

The editor downloads the current revision's JSON, thumbnail and images straight from storage.
The answer also names the account and workspace, so the editor keeps its offline cache apart
per account.
"""

import uuid

from sqlalchemy.orm import Session

from app.documents.models import Document
from app.documents.schemas import DocumentContentResponse, DocumentJson, RevisionImage, SignedFile
from app.documents.service.access import own_document_workspace
from app.documents.service.revisions import revision_files
from app.storage import service as storage


def open_document(
    db: Session, store: storage.ObjectStore, account_id: uuid.UUID, document_id: uuid.UUID
) -> DocumentContentResponse:
    """The current revision's files, signed for 10 minutes. A never-saved draft has none."""
    workspace_id = own_document_workspace(db, account_id, document_id)
    revision = db.get_one(Document, document_id).current_revision
    empty = DocumentContentResponse(
        document_id=document_id,
        workspace_id=workspace_id,
        account_id=account_id,
        revision=revision,
        document=None,
        thumbnail=None,
        images=[],
    )
    if revision is None:
        return empty

    files = revision_files(db, workspace_id, document_id, revision)
    signed = storage.sign_downloads(db, store, workspace_id, files.object_ids)
    document = signed[files.json_object_id]
    thumbnail = None if files.thumbnail_object_id is None else signed[files.thumbnail_object_id]
    return empty.model_copy(
        update={
            "document": DocumentJson(
                **_file(document), gzip=document.gzip, format_version=files.format_version
            ),
            "thumbnail": None if thumbnail is None else SignedFile(**_file(thumbnail)),
            "images": [
                RevisionImage(**_file(signed[object_id]), editor_hash=editor_hash)
                for editor_hash, object_id in files.images.items()
            ],
        }
    )


def _file(download: storage.SignedDownload) -> dict[str, object]:
    return {
        "url": download.url,
        "expires_at": download.expires_at,
        "sha256": download.sha256,
        "size_bytes": download.size_bytes,
        "mime_type": download.mime_type,
    }
