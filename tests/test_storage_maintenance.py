"""Storage cleanup run by the jobs queue (VEC-36): expiring saves, deleting unused files and
recounting quotas. Each must be safe to repeat and must never delete a file a revision uses.

Run as the platform database role acting for the workspace owner, as the worker does, so
row-level security applies.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import PLATFORM_ROLE, set_current_account
from app.documents.models import Workspace
from app.jobs.service.handlers import installed_handlers
from app.storage.models import (
    ByteReservation,
    ByteReservationStatus,
    DocumentSave,
    ObjectStatus,
    SaveStatus,
    StoredObject,
    Upload,
    UploadStatus,
    WorkspaceQuota,
)
from app.storage.service import (
    ObjectStoreError,
    delete_unused_objects,
    expire_uploads_and_reservations,
    reconcile_storage_quotas,
)
from app.storage.service.saves import object_key
from tests.conftest import as_role
from tests.factories import (
    make_document,
    make_object,
    make_quota,
    make_save,
    make_upload,
    make_workspace,
)
from tests.fake_storage import MemoryObjectStore

NOW = datetime.now(UTC)
LONG_AGO = NOW - timedelta(days=30)


@pytest.fixture
def workspace(db: Session) -> Workspace:
    workspace = make_workspace(db)
    make_quota(db, workspace, limit_bytes=10_000)
    as_role(db, PLATFORM_ROLE)
    set_current_account(db, workspace.owner_id)
    return workspace


def _quota(db: Session, workspace: Workspace) -> WorkspaceQuota:
    db.expire_all()
    return db.get_one(WorkspaceQuota, workspace.id)


def test_the_jobs_queue_finds_every_storage_cleanup() -> None:
    assert {
        "expire_uploads_and_reservations",
        "delete_unused_objects",
        "reconcile_storage_quotas",
    } <= installed_handlers().keys()


def _held_upload(db: Session, workspace: Workspace, expires_at: datetime) -> uuid.UUID:
    """A save still uploading one 300-byte file, with its space held."""
    save = make_save(db, make_document(db, workspace), expires_at=expires_at)
    upload = make_upload(db, workspace, save_id=save.id, max_bytes=300, expires_at=expires_at)
    db.add(
        ByteReservation(
            workspace_id=workspace.id,
            upload_id=upload.id,
            amount=300,
            status=ByteReservationStatus.RESERVED,
            expires_at=expires_at,
        )
    )
    _quota(db, workspace).reserved_bytes = 300
    db.flush()
    return save.id


def test_an_abandoned_save_expires_and_gives_its_space_back(
    db: Session, workspace: Workspace
) -> None:
    store = MemoryObjectStore()
    save_id = _held_upload(db, workspace, NOW - timedelta(minutes=1))
    upload = db.scalars(select(Upload)).one()
    store.files[upload.temp_key] = b"half an upload"

    expire_uploads_and_reservations(db, NOW, store)
    expire_uploads_and_reservations(db, NOW, store)  # a repeated run changes nothing

    db.expire_all()
    assert db.get_one(Upload, upload.id).status == UploadStatus.EXPIRED
    assert db.get_one(DocumentSave, save_id).status == SaveStatus.EXPIRED
    assert _quota(db, workspace).reserved_bytes == 0
    assert upload.temp_key in store.deleted and object_key(upload) in store.deleted
    assert store.files == {}


def test_a_save_still_in_time_is_left_alone(db: Session, workspace: Workspace) -> None:
    _held_upload(db, workspace, NOW + timedelta(minutes=10))

    expire_uploads_and_reservations(db, NOW, MemoryObjectStore())

    assert _quota(db, workspace).reserved_bytes == 300


def _unused(db: Session, workspace: Workspace, since: datetime | None) -> StoredObject:
    stored = make_object(db, workspace, unreferenced_since=since)
    _quota(db, workspace).used_bytes += stored.size_bytes
    db.flush()
    return stored


def test_unused_files_are_deleted_in_two_runs_and_used_files_never(
    db: Session, workspace: Workspace
) -> None:
    store = MemoryObjectStore()
    old = _unused(db, workspace, LONG_AGO)
    recent = _unused(db, workspace, NOW)
    in_use = _unused(db, workspace, None)
    for stored in (old, recent, in_use):
        store.files[stored.key] = b"bytes"
    cutoff = NOW - timedelta(days=8)

    delete_unused_objects(db, cutoff, store)
    db.expire_all()
    # First run: only marked, and no longer counted; the bytes are still there.
    assert db.get_one(StoredObject, old.id).status == ObjectStatus.PENDING_DELETION
    assert old.key in store.files
    assert _quota(db, workspace).used_bytes == recent.size_bytes + in_use.size_bytes

    delete_unused_objects(db, cutoff, store)
    db.expire_all()
    assert db.get_one(StoredObject, old.id).status == ObjectStatus.DELETED
    assert old.key not in store.files
    assert {db.get_one(StoredObject, o.id).status for o in (recent, in_use)} == {ObjectStatus.READY}
    assert set(store.files) == {recent.key, in_use.key}


def test_a_failed_deletion_never_leaves_a_ready_file_without_bytes(
    db: Session, workspace: Workspace
) -> None:
    store = MemoryObjectStore()
    old = _unused(db, workspace, LONG_AGO)
    delete_unused_objects(db, NOW, store)
    store.failing_deletes.add(old.key)

    with db.begin_nested():
        with pytest.raises(ObjectStoreError):
            delete_unused_objects(db, NOW, store)

    db.expire_all()
    assert db.get_one(StoredObject, old.id).status == ObjectStatus.PENDING_DELETION


def test_a_drifted_quota_is_recounted_from_files_and_reservations(
    db: Session, workspace: Workspace
) -> None:
    stored = _unused(db, workspace, None)
    make_object(db, workspace, status=ObjectStatus.DELETED)
    quota = _quota(db, workspace)
    quota.used_bytes, quota.reserved_bytes = 999, 77
    db.flush()

    reconcile_storage_quotas(db)
    reconcile_storage_quotas(db)

    quota = _quota(db, workspace)
    assert (quota.used_bytes, quota.reserved_bytes) == (stored.size_bytes, 0)
