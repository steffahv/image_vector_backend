"""Stored files: turning a checked upload into a file, reusing images, and locking files.

A stored file is `ready` from the moment it is recorded, with `unreferenced_since` set until a
revision uses it. The cleanup job only deletes files unreferenced for days, so a file that a save
in progress is about to use is never deleted under it.
"""

import logging
import uuid
from collections.abc import Collection, Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.storage.models import (
    ByteReservation,
    ByteReservationStatus,
    ObjectEncoding,
    ObjectKind,
    ObjectStatus,
    StoredObject,
    Upload,
    UploadStatus,
)
from app.storage.service.file_checks import ExpectedFile, check_file
from app.storage.service.object_store import ObjectStore, ObjectStoreError
from app.storage.service.quota import lock_quota
from app.storage.service.saves import now, object_key

logger = logging.getLogger(__name__)


class UploadMissing(Exception):
    """The browser has not uploaded the file yet (or the upload expired)."""


class ObjectUnavailable(Exception):
    """A file the save counted on is no longer ready (it was deleted meanwhile)."""


def find_ready_images(
    db: Session, workspace_id: uuid.UUID, hashes: Collection[bytes]
) -> dict[bytes, StoredObject]:
    """Images already stored in the workspace, by SHA-256: they are not uploaded again.

    Found images are marked as recently needed, so the cleanup job leaves them alone while the
    save that will use them is in progress.
    """
    if not hashes:
        return {}
    found = db.scalars(
        select(StoredObject).where(
            StoredObject.workspace_id == workspace_id,
            StoredObject.kind == ObjectKind.IMAGE,
            StoredObject.status == ObjectStatus.READY,
            StoredObject.sha256.in_(hashes),
        )
    ).all()
    _keep_alive(found)
    return {image.sha256: image for image in found}


def store_upload(
    db: Session, store: ObjectStore, upload_id: uuid.UUID, expected: ExpectedFile
) -> None:
    """Check an uploaded file and make it a stored file. Commits.

    The bytes are read once, checked, and those same bytes are written to the final key, so
    what is stored is exactly what was checked. Raises `UploadMissing` if nothing was uploaded
    and `FileRejected` if the bytes are not what was declared.
    """
    upload = db.get_one(Upload, upload_id)
    key = object_key(upload)
    try:
        data = store.read(upload.temp_key, max_bytes=upload.max_bytes)
        if data is None:
            raise UploadMissing(str(upload_id))
        check_file(data, expected)
        store.write(key, data, content_type=expected.mime_type)
    except (UploadMissing, ObjectStoreError):
        # Let the next commit try this file again right away instead of after the lease.
        _unclaim(upload)
        db.commit()
        raise

    stored_key = _record(db, upload.workspace_id, upload_id, key, store.bucket, expected)
    db.commit()
    if stored_key != key:
        # The same image was already stored: keep that one and drop this copy.
        delete_quietly(store, key)
    delete_quietly(store, upload.temp_key)


def _unclaim(upload: Upload) -> None:
    if upload.status == UploadStatus.VERIFYING:
        upload.status = UploadStatus.PENDING
        upload.lease_until = None


def _record(
    db: Session,
    workspace_id: uuid.UUID,
    upload_id: uuid.UUID,
    key: str,
    bucket: str,
    expected: ExpectedFile,
) -> str:
    """Point the upload to its stored file and move its held space to used. Returns the key."""
    quota = lock_quota(db, workspace_id)
    upload = db.scalar(select(Upload).where(Upload.id == upload_id).with_for_update())
    if upload is None:
        raise RuntimeError("The upload disappeared while it was checked")
    if upload.status != UploadStatus.VERIFYING:
        # Another commit finished (or the save ended) meanwhile; nothing left to do.
        existing = None if upload.object_id is None else db.get(StoredObject, upload.object_id)
        return key if existing is None else existing.key
    reservation = db.scalar(
        select(ByteReservation)
        .where(
            ByteReservation.upload_id == upload_id,
            ByteReservation.status == ByteReservationStatus.RESERVED,
        )
        .with_for_update()
    )
    held = 0 if reservation is None else reservation.amount
    same = (
        find_ready_images(db, workspace_id, [expected.sha256]).get(expected.sha256)
        if expected.kind == ObjectKind.IMAGE
        else None
    )
    if same is None:
        stored = _new_object(workspace_id, key, bucket, expected)
        db.add(stored)
        db.flush()
        quota.used_bytes += expected.size_bytes
        reservation_status = ByteReservationStatus.CONSUMED
    else:
        # Saved by another save meanwhile: one image is stored once per workspace.
        stored = same
        reservation_status = ByteReservationStatus.RELEASED
    quota.reserved_bytes -= held
    if reservation is not None:
        reservation.status = reservation_status
    upload.object_id = stored.id
    upload.status = UploadStatus.CONFIRMED
    upload.lease_until = None
    db.flush()
    return stored.key


def _new_object(
    workspace_id: uuid.UUID, key: str, bucket: str, expected: ExpectedFile
) -> StoredObject:
    checked_at = now()
    return StoredObject(
        workspace_id=workspace_id,
        kind=expected.kind,
        bucket=bucket,
        key=key,
        sha256=expected.sha256,
        size_bytes=expected.size_bytes,
        mime_type=expected.mime_type,
        encoding=ObjectEncoding.GZIP if expected.gzip else ObjectEncoding.IDENTITY,
        width=expected.width,
        height=expected.height,
        status=ObjectStatus.READY,
        verified_at=checked_at,
        unreferenced_since=checked_at,
    )


def uploaded_objects(db: Session, upload_ids: Collection[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
    """upload id -> stored file id, for confirmed uploads."""
    rows = db.execute(
        select(Upload.id, Upload.object_id).where(
            Upload.id.in_(upload_ids), Upload.status == UploadStatus.CONFIRMED
        )
    ).all()
    return {upload_id: object_id for upload_id, object_id in rows if object_id is not None}


def lock_ready_objects(
    db: Session, workspace_id: uuid.UUID, object_ids: Collection[uuid.UUID]
) -> list[StoredObject]:
    """Lock the files a revision will use, in id order, and check they are all still ready."""
    locked = db.scalars(
        select(StoredObject)
        .where(StoredObject.workspace_id == workspace_id, StoredObject.id.in_(object_ids))
        .order_by(StoredObject.id)
        .with_for_update()
    ).all()
    if len(locked) != len(set(object_ids)) or any(
        stored.status != ObjectStatus.READY for stored in locked
    ):
        raise ObjectUnavailable(str(workspace_id))
    return list(locked)


def mark_referenced(objects: Iterable[StoredObject]) -> None:
    """A revision now uses these files: the cleanup job must not delete them."""
    for stored in objects:
        stored.unreferenced_since = None


def _keep_alive(objects: Iterable[StoredObject]) -> None:
    for stored in objects:
        if stored.unreferenced_since is not None:
            stored.unreferenced_since = now()


def delete_quietly(store: ObjectStore, key: str) -> None:
    """Delete bytes nothing points to. The save must not fail over it, so a failure is only
    logged; temporary keys also expire with the bucket's rule for `uploads/`."""
    try:
        store.delete(key)
    except ObjectStoreError as error:
        logger.warning("Could not delete an unused key: %s", error)
