"""A workspace's storage space: its limit, the bytes stored and the bytes held by uploads.

Every write transaction of a save, and the cleanup jobs, lock the quota row first. That fixed
order (quota, then document, then files) is what keeps two saves of the same workspace from
deadlocking or passing the limit together.
"""

import uuid
from collections.abc import Collection

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.storage.models import ByteReservation, ByteReservationStatus, WorkspaceQuota


class QuotaMissing(Exception):
    """The workspace has no quota row, so nothing can be stored in it."""


class InsufficientStorage(Exception):
    """The files would pass the workspace's limit."""


def lock_quota(db: Session, workspace_id: uuid.UUID) -> WorkspaceQuota:
    quota = db.scalar(
        select(WorkspaceQuota).where(WorkspaceQuota.workspace_id == workspace_id).with_for_update()
    )
    if quota is None:
        raise QuotaMissing(str(workspace_id))
    return quota


def reserve_bytes(quota: WorkspaceQuota, amount: int) -> None:
    """Hold `amount` bytes, or refuse if stored + held + `amount` passes the limit.

    A workspace over its limit after a plan downgrade can still save nothing new, but keeps
    reading and deleting (the limit is never a CHECK, see WorkspaceQuota).
    """
    if quota.used_bytes + quota.reserved_bytes + amount > quota.limit_bytes:
        raise InsufficientStorage(str(quota.workspace_id))
    quota.reserved_bytes += amount


def release_reservations(
    db: Session, quota: WorkspaceQuota, upload_ids: Collection[uuid.UUID]
) -> None:
    """Give back the space still held for these uploads. Repeating it changes nothing."""
    if not upload_ids:
        return
    held = db.scalars(
        select(ByteReservation)
        .where(
            ByteReservation.upload_id.in_(upload_ids),
            ByteReservation.status == ByteReservationStatus.RESERVED,
        )
        .with_for_update()
    ).all()
    for reservation in held:
        reservation.status = ByteReservationStatus.RELEASED
        quota.reserved_bytes -= reservation.amount


def recount_reserved_bytes(db: Session, workspace_id: uuid.UUID) -> int:
    return (
        db.scalar(
            select(func.coalesce(func.sum(ByteReservation.amount), 0)).where(
                ByteReservation.workspace_id == workspace_id,
                ByteReservation.status == ByteReservationStatus.RESERVED,
            )
        )
        or 0
    )
