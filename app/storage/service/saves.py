"""The storage side of a save: the request, its uploads and the space they hold.

documents.service.save drives the flow and decides about documents and revisions; this file
only knows saves, uploads, reservations and keys. Functions that change rows expect the caller
to hold the workspace quota lock (`lock_quota`) and to commit.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.storage.models import (
    ByteReservation,
    ByteReservationStatus,
    DocumentSave,
    ObjectKind,
    SaveStatus,
    Upload,
    UploadStatus,
    WorkspaceQuota,
)
from app.storage.service.object_store import MAX_SIGNED_URL_TTL, ObjectStore, SignedUpload
from app.storage.service.quota import release_reservations, reserve_bytes

# How long a save may take from asking for URLs to committing. Its URLs are re-signed on
# request, each valid 10 minutes at most, until then.
SAVE_TTL = timedelta(minutes=30)
# How long a commit may spend checking one save's files before another commit may take over.
VERIFY_LEASE = timedelta(minutes=5)

_OPEN_UPLOAD = (UploadStatus.PENDING, UploadStatus.VERIFYING)


@dataclass(frozen=True)
class PlannedUpload:
    """A file of the save that is not stored yet, as the editor described it."""

    kind: ObjectKind
    sha256: bytes
    size_bytes: int


@dataclass(frozen=True)
class NewSave:
    workspace_id: uuid.UUID
    document_id: uuid.UUID
    account_id: uuid.UUID
    idempotency_key: uuid.UUID
    fingerprint: bytes
    base_revision: int
    manifest: dict[str, Any]


def upload_key(workspace_id: uuid.UUID) -> str:
    """Where the browser uploads: a temporary key, never built from user text."""
    return f"uploads/{workspace_id}/{uuid.uuid4()}"


def object_key(upload: Upload) -> str:
    """The final, immutable key of the bytes checked for `upload`.

    Derived from the upload, so a retried or concurrent check of the same upload writes the same
    key with the same bytes, and a crash between writing it and recording it leaves a key that
    the upload still names.
    """
    return f"objects/{upload.workspace_id}/{upload.id}"


def now() -> datetime:
    return datetime.now(UTC)


def find_save(
    db: Session, document_id: uuid.UUID, idempotency_key: uuid.UUID
) -> DocumentSave | None:
    return db.scalar(
        select(DocumentSave).where(
            DocumentSave.document_id == document_id,
            DocumentSave.idempotency_key == idempotency_key,
        )
    )


def get_save(
    db: Session,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    save_id: uuid.UUID,
    *,
    lock: bool = False,
) -> DocumentSave | None:
    query = select(DocumentSave).where(
        DocumentSave.id == save_id,
        DocumentSave.workspace_id == workspace_id,
        DocumentSave.document_id == document_id,
    )
    return db.scalar(query.with_for_update() if lock else query)


def open_save(
    db: Session, quota: WorkspaceQuota, new: NewSave, planned: list[PlannedUpload]
) -> DocumentSave:
    """Record the save, one upload per file and the space they hold, or refuse for space."""
    reserve_bytes(quota, sum(file.size_bytes for file in planned))
    expires_at = now() + SAVE_TTL
    save = DocumentSave(
        workspace_id=new.workspace_id,
        document_id=new.document_id,
        account_id=new.account_id,
        idempotency_key=new.idempotency_key,
        request_fingerprint=new.fingerprint,
        base_revision=new.base_revision,
        manifest=new.manifest,
        status=SaveStatus.PREPARING,
        expires_at=expires_at,
    )
    db.add(save)
    db.flush()
    uploads = [
        Upload(
            workspace_id=new.workspace_id,
            account_id=new.account_id,
            save_id=save.id,
            kind=file.kind,
            temp_key=upload_key(new.workspace_id),
            max_bytes=file.size_bytes,
            declared_sha256=file.sha256,
            status=UploadStatus.PENDING,
            expires_at=expires_at,
        )
        for file in planned
    ]
    db.add_all(uploads)
    db.flush()
    db.add_all(
        ByteReservation(
            workspace_id=new.workspace_id,
            upload_id=upload.id,
            amount=upload.max_bytes,
            status=ByteReservationStatus.RESERVED,
            expires_at=expires_at,
        )
        for upload in uploads
    )
    db.flush()
    return save


def save_uploads(db: Session, save: DocumentSave) -> list[Upload]:
    return list(
        db.scalars(
            select(Upload)
            .where(Upload.workspace_id == save.workspace_id, Upload.save_id == save.id)
            .order_by(Upload.id)
        )
    )


def sign_upload(
    store: ObjectStore, upload: Upload, save: DocumentSave, content_type: str
) -> tuple[SignedUpload, datetime]:
    """A signed PUT for an upload still to send, valid until the save expires at the latest."""
    expires_at = min(now() + MAX_SIGNED_URL_TTL, save.expires_at)
    signed = store.sign_upload(
        upload.temp_key,
        content_type=content_type,
        size_bytes=upload.max_bytes,
        expires_in=expires_at - now(),
    )
    return signed, expires_at


def claim_uploads(db: Session, save: DocumentSave) -> list[Upload]:
    """Take the save's uploads that nobody is checking, so one commit checks each file.

    A lease that ran out (a commit that crashed or hung) can be taken over.
    """
    claimed = list(
        db.scalars(
            select(Upload)
            .where(
                Upload.workspace_id == save.workspace_id,
                Upload.save_id == save.id,
                or_(
                    Upload.status == UploadStatus.PENDING,
                    (Upload.status == UploadStatus.VERIFYING) & (Upload.lease_until <= now()),
                ),
            )
            .order_by(Upload.id)
            .with_for_update()
        )
    )
    for upload in claimed:
        upload.status = UploadStatus.VERIFYING
        upload.lease_until = now() + VERIFY_LEASE
    db.flush()
    return claimed


def has_open_uploads(db: Session, save: DocumentSave) -> bool:
    return (
        db.scalar(
            select(Upload.id)
            .where(
                Upload.workspace_id == save.workspace_id,
                Upload.save_id == save.id,
                Upload.status.in_(_OPEN_UPLOAD),
            )
            .limit(1)
        )
        is not None
    )


def end_save(
    db: Session, quota: WorkspaceQuota, save: DocumentSave, status: SaveStatus
) -> list[Upload]:
    """Close a save that will not publish (expired, canceled or in conflict).

    Its open uploads end too and the space they hold is given back. Returns the uploads that
    were still open, whose temporary keys the caller may delete.
    """
    save.status = status
    upload_status = UploadStatus.EXPIRED if status == SaveStatus.EXPIRED else UploadStatus.REJECTED
    open_uploads = [upload for upload in save_uploads(db, save) if upload.status in _OPEN_UPLOAD]
    for upload in open_uploads:
        upload.status = upload_status
        upload.lease_until = None
        if upload_status == UploadStatus.REJECTED and upload.error_code is None:
            upload.error_code = "save_" + status.value
    release_reservations(db, quota, [upload.id for upload in open_uploads])
    db.flush()
    return open_uploads


def confirm_save(save: DocumentSave, revision: int) -> None:
    save.status = SaveStatus.CONFIRMED
    save.result_revision = revision
