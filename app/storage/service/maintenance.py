"""Cleanup the jobs queue (VEC-36) runs for each workspace, as the workspace's owner.

Each function works on the workspaces the session's account can see, in bounded batches, and
can be repeated without harm: a retried or overlapping run finds nothing left to do. The jobs
module finds them by name (app/jobs/service/handlers.py).
"""

import logging
from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import ColumnElement, func, select
from sqlalchemy.orm import Session

from app.storage.models import (
    ByteReservation,
    ByteReservationStatus,
    DocumentSave,
    ObjectKind,
    ObjectStatus,
    SaveStatus,
    StoredObject,
    WorkspaceQuota,
)
from app.storage.service.object_store import ObjectStore, get_object_store
from app.storage.service.objects import delete_quietly
from app.storage.service.quota import lock_quota, recount_reserved_bytes, release_reservations
from app.storage.service.saves import end_save, now, object_key

logger = logging.getLogger(__name__)

BATCH_SIZE = 500


def _workspaces(db: Session) -> Sequence[WorkspaceQuota]:
    return db.scalars(select(WorkspaceQuota).order_by(WorkspaceQuota.workspace_id)).all()


def expire_uploads_and_reservations(
    db: Session, as_of: datetime, store: ObjectStore | None = None
) -> None:
    """End saves that were not committed in time and give back the space they held.

    The previous revision stays the current one. Also releases any reservation past its
    deadline whose save is already closed, and deletes the temporary and half-written keys of
    the expired uploads.
    """
    keys: list[str] = []
    for workspace in _workspaces(db):
        quota = lock_quota(db, workspace.workspace_id)
        saves = db.scalars(
            select(DocumentSave)
            .where(
                DocumentSave.workspace_id == quota.workspace_id,
                DocumentSave.status == SaveStatus.PREPARING,
                DocumentSave.expires_at <= as_of,
            )
            .order_by(DocumentSave.id)
            .limit(BATCH_SIZE)
            .with_for_update(skip_locked=True)
        ).all()
        for save in saves:
            for upload in end_save(db, quota, save, SaveStatus.EXPIRED):
                keys += [upload.temp_key, object_key(upload)]
        overdue = db.scalars(
            select(ByteReservation.upload_id)
            .where(
                ByteReservation.workspace_id == quota.workspace_id,
                ByteReservation.status == ByteReservationStatus.RESERVED,
                ByteReservation.expires_at <= as_of,
            )
            .limit(BATCH_SIZE)
        ).all()
        release_reservations(db, quota, overdue)
    db.flush()
    if keys:
        target = store or get_object_store()
        for key in keys:
            delete_quietly(target, key)


def delete_unused_objects(
    db: Session, older_than: datetime, store: ObjectStore | None = None
) -> None:
    """Delete files no revision has used since before `older_than`, in two runs.

    A run first deletes the bytes of files an earlier run marked `pending_deletion`, then marks
    the next ones. Marking and deleting never happen in the same transaction: if a deletion
    fails and the transaction rolls back, the files stay `pending_deletion`, never `ready`
    without bytes, so no save can reuse them. Exports are left to the exports module.
    """
    target = store
    for workspace in _workspaces(db):
        # Quota first, as every save does, so this never deadlocks with a save's commit.
        quota = lock_quota(db, workspace.workspace_id)
        marked = _objects(db, quota, StoredObject.status == ObjectStatus.PENDING_DELETION)
        if marked:
            target = target or get_object_store()
            for stored in marked:
                target.delete(stored.key)
                stored.status = ObjectStatus.DELETED
                stored.deleted_at = now()
        unused = _objects(
            db,
            quota,
            StoredObject.status == ObjectStatus.READY,
            StoredObject.kind != ObjectKind.EXPORT,
            StoredObject.unreferenced_since < older_than,
        )
        for stored in unused:
            stored.status = ObjectStatus.PENDING_DELETION
            quota.used_bytes = max(quota.used_bytes - stored.size_bytes, 0)
    db.flush()


def _objects(
    db: Session, quota: WorkspaceQuota, *conditions: ColumnElement[bool]
) -> Sequence[StoredObject]:
    return db.scalars(
        select(StoredObject)
        .where(StoredObject.workspace_id == quota.workspace_id, *conditions)
        .order_by(StoredObject.id)
        .limit(BATCH_SIZE)
        .with_for_update(skip_locked=True)
    ).all()


def reconcile_storage_quotas(db: Session) -> None:
    """Recount used and held bytes from the files and reservations, and fix any drift."""
    for workspace in _workspaces(db):
        quota = lock_quota(db, workspace.workspace_id)
        used = (
            db.scalar(
                select(func.coalesce(func.sum(StoredObject.size_bytes), 0)).where(
                    StoredObject.workspace_id == quota.workspace_id,
                    StoredObject.status == ObjectStatus.READY,
                )
            )
            or 0
        )
        reserved = recount_reserved_bytes(db, quota.workspace_id)
        if (used, reserved) != (quota.used_bytes, quota.reserved_bytes):
            logger.warning(
                "Storage quota of workspace %s drifted: used %s -> %s, reserved %s -> %s",
                quota.workspace_id,
                quota.used_bytes,
                used,
                quota.reserved_bytes,
                reserved,
            )
            quota.used_bytes = used
            quota.reserved_bytes = reserved
    db.flush()
