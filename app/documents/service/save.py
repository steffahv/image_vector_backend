"""Saving a document (Arquitectura §III-A, VEC-31): prepare, upload to signed URLs, commit.

1. `create_save`: checks the document and its base revision, holds the space and returns one
   signed URL per file still to upload. A retry with the same idempotency key returns the same
   save instead of a second one.
2. The browser uploads straight to storage, to temporary keys.
3. `commit_save`: checks every uploaded file against what was declared and copies it to its
   final key, then, in one short transaction that locks quota, document and files in that
   order, checks that nobody saved another revision meanwhile and publishes the new one.

Only a `confirmed` save is saved. A save that conflicts, fails its checks or expires never
changes the document; the space it held is given back and its unused files are cleaned later.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.documents.models import Document
from app.documents.schemas import SaveCreate, SaveResponse, UploadRole, UploadTarget
from app.documents.schemas.save import ImageFile, SavedFile
from app.documents.service.access import (
    lock_document,
    lock_quota,
    own_document_workspace,
)
from app.documents.service.revisions import RevisionFiles, publish_revision
from app.storage import service as storage
from app.storage.models import (
    DocumentSave,
    ObjectKind,
    SaveStatus,
    Upload,
    UploadStatus,
    WorkspaceQuota,
)

_ROLES = {
    ObjectKind.DOCUMENT_JSON: UploadRole.DOCUMENT,
    ObjectKind.THUMBNAIL: UploadRole.THUMBNAIL,
    ObjectKind.IMAGE: UploadRole.IMAGE,
}


class SaveNotFound(Exception):
    pass


@dataclass
class SaveConflict(Exception):
    """Another revision was saved since the save's base revision."""

    current_revision: int


class IdempotencyKeyReused(Exception):
    """The idempotency key was already used for a different request."""


class SaveFilesMissing(Exception):
    """Some files were not uploaded yet. The save stays open: upload them and commit again."""


@dataclass
class SaveRejected(Exception):
    """The save cannot publish (a file did not match, or a stored file is gone). Start over."""

    reason: str


class SaveExpired(Exception):
    pass


def create_save(
    db: Session,
    store: storage.ObjectStore,
    account_id: uuid.UUID,
    document_id: uuid.UUID,
    request: SaveCreate,
) -> tuple[SaveResponse, bool]:
    """Start a save, or return the one already made with this idempotency key.

    Returns the save and whether it was created now (False for a retry).
    """
    workspace_id = own_document_workspace(db, account_id, document_id)
    quota = lock_quota(db, workspace_id)
    fingerprint = _fingerprint(request)
    existing = storage.find_save(db, document_id, request.idempotency_key)
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise IdempotencyKeyReused(str(document_id))
        response = _response(db, store, existing)
        db.commit()
        return response, False

    document = lock_document(db, workspace_id, document_id)
    current = document.current_revision or 0
    if request.base_revision != current:
        raise SaveConflict(current)

    declared = _declared_files(request)
    stored_images = storage.find_ready_images(
        db, workspace_id, [d.file_hash for d in declared if d.kind == ObjectKind.IMAGE]
    )
    planned = [
        storage.PlannedUpload(d.kind, d.file_hash, d.file.size_bytes)
        for d in declared
        if d.file_hash not in stored_images or d.kind != ObjectKind.IMAGE
    ]
    save = storage.open_save(
        db,
        quota,
        storage.NewSave(
            workspace_id=workspace_id,
            document_id=document_id,
            account_id=account_id,
            idempotency_key=request.idempotency_key,
            fingerprint=fingerprint,
            base_revision=request.base_revision,
            manifest=request.model_dump(mode="json", exclude={"idempotency_key"}),
        ),
        planned,
    )
    response = _response(db, store, save)
    db.commit()
    return response, True


def read_save(
    db: Session,
    store: storage.ObjectStore,
    account_id: uuid.UUID,
    document_id: uuid.UUID,
    save_id: uuid.UUID,
) -> SaveResponse:
    workspace_id = own_document_workspace(db, account_id, document_id, include_trash=True)
    save = storage.get_save(db, workspace_id, document_id, save_id)
    if save is None:
        raise SaveNotFound(str(save_id))
    return _response(db, store, save)


def commit_save(
    db: Session,
    store: storage.ObjectStore,
    account_id: uuid.UUID,
    document_id: uuid.UUID,
    save_id: uuid.UUID,
) -> SaveResponse:
    """Check the uploaded files and publish the revision. Safe to repeat.

    While another commit of the same save is still checking files, this one answers the save
    as `preparing` instead of waiting; the editor asks again.
    """
    workspace_id = own_document_workspace(db, account_id, document_id)
    quota = lock_quota(db, workspace_id)
    save = _open_save(db, quota, workspace_id, document_id, save_id)
    if save.status == SaveStatus.CONFIRMED:
        response = _response(db, store, save)
        db.commit()
        return response
    claimed = storage.claim_uploads(db, save)
    db.commit()

    request = _request(save)
    missing = False
    for upload in claimed:
        try:
            storage.store_upload(db, store, upload.id, _expected(request, upload))
        except storage.UploadMissing:
            missing = True
        except storage.FileRejected as rejected:
            _reject(db, workspace_id, document_id, save_id, upload.id, rejected.code)
            raise SaveRejected(
                f"A file does not match what was declared ({rejected.code})"
            ) from rejected

    if storage.has_open_uploads(db, save):
        db.commit()
        if missing:
            raise SaveFilesMissing(str(save_id))
        return _response(db, store, save)
    return _publish(db, store, workspace_id, document_id, save_id, account_id)


def _publish(
    db: Session,
    store: storage.ObjectStore,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    save_id: uuid.UUID,
    account_id: uuid.UUID,
) -> SaveResponse:
    """The short transaction: lock quota, document and files, check the base, publish."""
    quota = lock_quota(db, workspace_id)
    document = lock_document(db, workspace_id, document_id)
    save = _open_save(db, quota, workspace_id, document_id, save_id)
    if save.status == SaveStatus.CONFIRMED:
        response = _response(db, store, save)
        db.commit()
        return response
    current = document.current_revision or 0
    if save.base_revision != current:
        storage.end_save(db, quota, save, SaveStatus.CONFLICT)
        db.commit()
        raise SaveConflict(current)

    request = _request(save)
    try:
        files = _revision_files(db, workspace_id, save, request)
        revision = publish_revision(db, document, files, account_id)
    except storage.ObjectUnavailable:
        storage.end_save(db, quota, save, SaveStatus.CANCELED)
        db.commit()
        raise SaveRejected("A stored file is no longer available") from None
    storage.confirm_save(save, revision)
    db.flush()
    response = _response(db, store, save)
    db.commit()
    return response


# Keys of the save's files besides images, which go by their SHA-256 in hex.
_DOCUMENT = "document"
_THUMBNAIL = "thumbnail"


def _revision_files(
    db: Session, workspace_id: uuid.UUID, save: DocumentSave, request: SaveCreate
) -> RevisionFiles:
    """Which stored file holds each file of the request."""
    uploads = storage.save_uploads(db, save)
    stored = storage.uploaded_objects(db, [upload.id for upload in uploads])
    by_hash: dict[str, uuid.UUID] = {}
    files: dict[str, uuid.UUID] = {}
    for upload in uploads:
        object_id = stored.get(upload.id)
        if object_id is None:
            raise RuntimeError("Publishing a save with an unconfirmed upload")
        if upload.kind == ObjectKind.DOCUMENT_JSON:
            files[_DOCUMENT] = object_id
        elif upload.kind == ObjectKind.THUMBNAIL:
            files[_THUMBNAIL] = object_id
        elif upload.declared_sha256 is not None:
            by_hash[upload.declared_sha256.hex()] = object_id
    reused = {image.sha256 for image in request.images} - by_hash.keys()
    found = storage.find_ready_images(db, workspace_id, [bytes.fromhex(h) for h in reused])
    by_hash |= {sha256.hex(): image.id for sha256, image in found.items()}
    if reused - by_hash.keys():
        # An image that was stored when the save started is gone now.
        raise storage.ObjectUnavailable(str(workspace_id))
    return RevisionFiles(
        json_object_id=files[_DOCUMENT],
        thumbnail_object_id=files.get(_THUMBNAIL),
        format_version=request.document.format_version,
        original_json_bytes=request.document.original_bytes,
        images={image.editor_hash: by_hash[image.sha256] for image in request.images},
    )


def _open_save(
    db: Session,
    quota: WorkspaceQuota,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    save_id: uuid.UUID,
) -> DocumentSave:
    """The locked save, if it can still be committed (or already was)."""
    save = storage.get_save(db, workspace_id, document_id, save_id, lock=True)
    if save is None:
        raise SaveNotFound(str(save_id))
    if save.status == SaveStatus.PREPARING and save.expires_at <= datetime.now(UTC):
        storage.end_save(db, quota, save, SaveStatus.EXPIRED)
        db.commit()
        raise SaveExpired(str(save_id))
    if save.status == SaveStatus.CONFLICT:
        current = db.scalar(select(Document.current_revision).where(Document.id == document_id))
        raise SaveConflict(current or 0)
    if save.status == SaveStatus.EXPIRED:
        raise SaveExpired(str(save_id))
    if save.status == SaveStatus.CANCELED:
        raise SaveRejected("The save was canceled; start a new one")
    return save


def _reject(
    db: Session,
    workspace_id: uuid.UUID,
    document_id: uuid.UUID,
    save_id: uuid.UUID,
    upload_id: uuid.UUID,
    code: str,
) -> None:
    quota = lock_quota(db, workspace_id)
    save = storage.get_save(db, workspace_id, document_id, save_id, lock=True)
    if save is None or save.status != SaveStatus.PREPARING:
        db.commit()
        return
    upload = db.get_one(Upload, upload_id)
    upload.error_code = code
    storage.end_save(db, quota, save, SaveStatus.CANCELED)
    db.commit()


def _fingerprint(request: SaveCreate) -> bytes:
    """What a retry must repeat exactly to count as the same save."""
    body = request.model_dump_json(exclude={"idempotency_key"})
    return hashlib.sha256(body.encode()).digest()


def _request(save: DocumentSave) -> SaveCreate:
    return SaveCreate.model_validate(save.manifest | {"idempotency_key": save.idempotency_key})


@dataclass(frozen=True)
class _DeclaredFile:
    kind: ObjectKind
    file: SavedFile

    @property
    def file_hash(self) -> bytes:
        return bytes.fromhex(self.file.sha256)


def _declared_files(request: SaveCreate) -> list[_DeclaredFile]:
    """Each distinct file of the request once: images with equal bytes are one file."""
    files = [_DeclaredFile(ObjectKind.DOCUMENT_JSON, request.document)]
    if request.thumbnail is not None:
        files.append(_DeclaredFile(ObjectKind.THUMBNAIL, request.thumbnail))
    seen: set[str] = set()
    for image in request.images:
        if image.sha256 not in seen:
            seen.add(image.sha256)
            files.append(_DeclaredFile(ObjectKind.IMAGE, image))
    return files


def _expected(request: SaveCreate, upload: Upload) -> storage.ExpectedFile:
    """What the upload must contain, from the request stored with the save."""
    if upload.kind == ObjectKind.DOCUMENT_JSON:
        document = request.document
        return storage.ExpectedFile(
            kind=upload.kind,
            sha256=bytes.fromhex(document.sha256),
            size_bytes=document.size_bytes,
            mime_type=document.mime_type,
            gzip=document.gzip,
            original_bytes=document.original_bytes,
        )
    image = request.thumbnail if upload.kind == ObjectKind.THUMBNAIL else _image(request, upload)
    if image is None:
        raise RuntimeError("An upload that is not in the save request")
    return storage.ExpectedFile(
        kind=upload.kind,
        sha256=bytes.fromhex(image.sha256),
        size_bytes=image.size_bytes,
        mime_type=image.mime_type,
        width=image.width,
        height=image.height,
    )


def _image(request: SaveCreate, upload: Upload) -> ImageFile | None:
    """The first image of the request with the upload's bytes (equal bytes upload once)."""
    if upload.declared_sha256 is None:
        return None
    sha256 = upload.declared_sha256.hex()
    return next((image for image in request.images if image.sha256 == sha256), None)


def _target(
    store: storage.ObjectStore, save: DocumentSave, request: SaveCreate, upload: Upload
) -> UploadTarget:
    mime_type: str
    editor_hash: str | None = None
    if upload.kind == ObjectKind.DOCUMENT_JSON:
        mime_type = request.document.mime_type
    else:
        file = request.thumbnail if upload.kind == ObjectKind.THUMBNAIL else _image(request, upload)
        if file is None:
            raise RuntimeError("An upload that is not in the save request")
        mime_type = file.mime_type
        editor_hash = file.editor_hash if isinstance(file, ImageFile) else None
    signed, expires_at = storage.sign_upload(store, upload, save, mime_type)
    return UploadTarget(
        upload_id=upload.id,
        role=_ROLES[upload.kind],
        editor_hash=editor_hash,
        method="PUT",
        url=signed.url,
        headers=signed.headers,
        expires_at=expires_at,
    )


def _response(db: Session, store: storage.ObjectStore, save: DocumentSave) -> SaveResponse:
    targets: list[UploadTarget] = []
    if save.status == SaveStatus.PREPARING:
        request = _request(save)
        for upload in storage.save_uploads(db, save):
            if upload.status == UploadStatus.PENDING:
                targets.append(_target(store, save, request, upload))
    return SaveResponse(
        id=save.id,
        document_id=save.document_id,
        status=save.status,
        base_revision=save.base_revision,
        revision=save.result_revision,
        uploads=targets,
        expires_at=save.expires_at,
    )
