"""Saving a document (VEC-31): nothing is lost or duplicated, whatever step fails.

Requests run as the platform database role, not as the superuser tests connect with, so
row-level security applies as in production (see tests/document_api.py).
"""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, text, update
from sqlalchemy.orm import Session

from app.auth.service import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.db import PLATFORM_ROLE, set_current_account
from app.documents.models import Document, DocumentRevision, DocumentStatus, RevisionImage
from app.documents.router.responses import object_store
from app.main import app
from app.storage.models import (
    ByteReservation,
    ByteReservationStatus,
    DocumentSave,
    ObjectKind,
    ObjectStatus,
    SaveStatus,
    StoredObject,
    Upload,
    UploadStatus,
    WorkspaceQuota,
)
from tests.conftest import as_role
from tests.document_api import Api, Draft, png
from tests.factories import make_account

# The whole flow


def test_a_draft_is_saved_and_becomes_revision_1(api: Api) -> None:
    draft = Draft.of()
    prepared = api.prepare(draft)
    assert prepared.status_code == 201
    roles = sorted(target["role"] for target in prepared.json()["uploads"])
    assert roles == ["document", "image", "thumbnail"]
    total = len(draft.document) + len(draft.thumbnail or b"") + len(draft.images["img-1"])
    assert api.quota().reserved_bytes == total

    api.upload(draft, prepared.json())
    committed = api.commit(prepared.json()["id"])

    assert committed.status_code == 200, committed.text
    assert committed.json() | {"uploads": []} == committed.json()
    assert (committed.json()["status"], committed.json()["revision"]) == ("confirmed", 1)
    api.db.expire_all()
    document = api.db.get_one(Document, api.document.id)
    assert (document.current_revision, document.status) == (1, DocumentStatus.ACTIVE)
    images = api.db.scalars(select(RevisionImage)).all()
    assert [(image.revision, image.editor_hash) for image in images] == [(1, "img-1")]
    quota = api.quota()
    assert (quota.used_bytes, quota.reserved_bytes) == (total, 0)
    # The temporary keys are gone; the files live under their final keys, all referenced.
    assert all(key.startswith("objects/") for key in api.store.files)
    stored = api.db.scalars(select(StoredObject)).all()
    assert len(stored) == 3
    assert all(o.unreferenced_since is None and o.status == ObjectStatus.READY for o in stored)


def test_the_next_save_builds_on_the_current_revision(api: Api) -> None:
    assert api.save(Draft.of()).json()["revision"] == 1
    second = api.save(Draft.of({"pages": []}), base_revision=1)

    assert second.json()["revision"] == 2
    assert api.current_revision() == 2


# Lost responses and retries


def test_a_retried_prepare_returns_the_same_save_without_holding_space_twice(api: Api) -> None:
    draft = Draft.of()
    first = api.prepare(draft)
    again = api.prepare(draft)

    assert (first.status_code, again.status_code) == (201, 200)
    assert again.json()["id"] == first.json()["id"]
    assert api.count(DocumentSave) == 1
    assert api.count(Upload) == 3
    total = len(draft.document) + len(draft.thumbnail or b"") + len(draft.images["img-1"])
    assert api.quota().reserved_bytes == total


def test_a_retry_after_a_lost_commit_answer_returns_the_saved_revision(api: Api) -> None:
    draft = Draft.of()
    prepared = api.prepare(draft)
    api.upload(draft, prepared.json())
    api.commit(prepared.json()["id"])

    commit_again = api.commit(prepared.json()["id"])
    prepare_again = api.prepare(draft)

    assert (commit_again.json()["status"], commit_again.json()["revision"]) == ("confirmed", 1)
    assert (prepare_again.status_code, prepare_again.json()["revision"]) == (200, 1)
    assert api.count(DocumentRevision) == 1
    assert api.current_revision() == 1


def test_an_idempotency_key_reused_for_another_request_is_refused(api: Api) -> None:
    draft = Draft.of()
    api.prepare(draft)
    other = Draft.of({"pages": []})
    other.idempotency_key = draft.idempotency_key

    response = api.prepare(other)

    assert response.status_code == 422
    assert api.count(DocumentSave) == 1


# Two devices


def test_a_save_from_a_stale_revision_conflicts_and_never_overwrites(api: Api) -> None:
    laptop, phone = Draft.of({"from": "laptop"}), Draft.of({"from": "phone"})
    laptop_save = api.prepare(laptop).json()
    phone_save = api.prepare(phone).json()
    api.upload(laptop, laptop_save)
    api.upload(phone, phone_save)

    assert api.commit(laptop_save["id"]).json()["revision"] == 1
    conflict = api.commit(phone_save["id"])

    assert conflict.status_code == 409
    assert conflict.json()["current_revision"] == 1
    assert api.current_revision() == 1
    assert api.count(DocumentRevision) == 1
    assert api.db.get_one(DocumentSave, uuid.UUID(phone_save["id"])).status == SaveStatus.CONFLICT
    assert api.quota().reserved_bytes == 0
    # Asking again gives the same answer, not a second attempt.
    assert api.commit(phone_save["id"]).status_code == 409


def test_preparing_from_a_stale_revision_conflicts_before_anything_is_held(api: Api) -> None:
    api.save(Draft.of())

    response = api.prepare(Draft.of({"pages": []}), base_revision=0)

    assert response.status_code == 409
    assert response.json()["current_revision"] == 1
    assert api.count(DocumentSave) == 1
    assert api.quota().reserved_bytes == 0


# Uploads that fail or stop half way


def test_a_commit_before_every_file_is_uploaded_keeps_the_save_open(api: Api) -> None:
    draft = Draft.of()
    prepared = api.prepare(draft).json()
    api.upload(draft, prepared, skip="image")

    missing = api.commit(prepared["id"])

    assert missing.status_code == 422
    assert api.current_revision() is None
    reread = api.client.get(f"{api.doc_url}/saves/{prepared['id']}").json()
    assert reread["status"] == "preparing"
    assert [target["role"] for target in reread["uploads"]] == ["image"]

    api.upload(draft, reread)
    assert api.commit(prepared["id"]).json()["revision"] == 1


def _flip_last_byte(data: bytes) -> bytes:
    return data[:-1] + bytes([data[-1] ^ 1])


@pytest.mark.parametrize(
    ("role", "tamper", "code"),
    [
        ("image", _flip_last_byte, "hash_mismatch"),
        ("document", lambda data: data[:-1], "size_mismatch"),
    ],
)
def test_a_file_that_is_not_what_was_declared_cancels_the_save(
    api: Api, role: str, tamper: Callable[[bytes], bytes], code: str
) -> None:
    draft = Draft.of()
    prepared = api.prepare(draft).json()
    api.upload(draft, prepared)
    target = next(t for t in prepared["uploads"] if t["role"] == role)
    key = api.store.key_of(target["url"])
    api.store.files[key] = tamper(api.store.files[key])

    response = api.commit(prepared["id"])

    assert response.status_code == 422
    assert code in response.json()["detail"]
    assert api.current_revision() is None
    save = api.db.get_one(DocumentSave, uuid.UUID(prepared["id"]))
    assert save.status == SaveStatus.CANCELED
    rejected = api.db.get_one(Upload, uuid.UUID(target["upload_id"]))
    assert (rejected.status, rejected.error_code) == (UploadStatus.REJECTED, code)
    assert api.quota().reserved_bytes == 0
    assert api.commit(prepared["id"]).status_code == 422


def test_a_commit_of_an_expired_save_gives_the_space_back(api: Api) -> None:
    draft = Draft.of()
    prepared = api.prepare(draft).json()
    api.upload(draft, prepared)
    api.db.execute(update(DocumentSave).values(expires_at=datetime.now(UTC) - timedelta(seconds=1)))

    response = api.commit(prepared["id"])

    assert response.status_code == 410
    assert api.current_revision() is None
    assert api.quota().reserved_bytes == 0
    assert api.count(Upload, Upload.status == UploadStatus.EXPIRED) == 3


def test_a_file_another_commit_is_checking_is_not_checked_twice(api: Api) -> None:
    draft = Draft.of()
    prepared = api.prepare(draft).json()
    api.upload(draft, prepared)
    api.db.execute(
        update(Upload).values(
            status=UploadStatus.VERIFYING, lease_until=datetime.now(UTC) + timedelta(minutes=1)
        )
    )

    busy = api.commit(prepared["id"])
    assert (busy.status_code, busy.json()["status"]) == (200, "preparing")

    # A commit that crashed loses its lease, and the next one takes over.
    api.db.execute(update(Upload).values(lease_until=datetime.now(UTC) - timedelta(seconds=1)))
    assert api.commit(prepared["id"]).json()["revision"] == 1


# Space


def test_a_save_that_would_pass_the_limit_is_refused_before_any_upload(api: Api) -> None:
    set_current_account(api.db, api.account.id)
    api.db.execute(update(WorkspaceQuota).values(limit_bytes=100))

    response = api.prepare(Draft.of())

    assert response.status_code == 507
    assert api.count(DocumentSave) == 0
    assert api.quota().reserved_bytes == 0


# One image, stored once


def test_an_image_used_in_several_revisions_is_stored_once(api: Api) -> None:
    logo = png(5, 5, (0, 255, 0))
    api.save(Draft.of(images={"logo": logo}))

    second = Draft.of({"pages": []}, images={"logo-again": logo})
    prepared = api.prepare(second, base_revision=1).json()

    assert "image" not in [target["role"] for target in prepared["uploads"]]
    api.upload(second, prepared)
    assert api.commit(prepared["id"]).json()["revision"] == 2
    image_objects = api.db.scalars(
        select(StoredObject).where(StoredObject.kind == ObjectKind.IMAGE)
    ).all()
    assert len(image_objects) == 1
    maps = api.db.scalars(select(RevisionImage.image_object_id)).all()
    assert set(maps) == {image_objects[0].id}


def test_the_same_image_uploaded_by_two_saves_at_once_is_kept_once(api: Api) -> None:
    logo = png(5, 5, (0, 255, 0))
    first, second = Draft.of(images={"a": logo}), Draft.of({"pages": []}, images={"b": logo})
    first_save, second_save = api.prepare(first).json(), api.prepare(second).json()
    api.upload(first, first_save)
    api.upload(second, second_save)

    api.commit(first_save["id"])
    conflict = api.commit(second_save["id"])

    assert conflict.status_code == 409
    assert api.count(StoredObject, StoredObject.kind == ObjectKind.IMAGE) == 1
    # The second copy was dropped and its space given back; the image counts once.
    image_keys = [k for k in api.store.files if k.startswith("objects/")]
    assert len(image_keys) == api.count(StoredObject)
    stored = api.db.scalar(select(func.sum(StoredObject.size_bytes))) or 0
    assert api.quota().used_bytes == stored
    assert api.count(ByteReservation, ByteReservation.status == ByteReservationStatus.RESERVED) == 0


# Ownership


def test_another_accounts_document_and_saves_are_not_found(api: Api, db: Session) -> None:
    draft = Draft.of()
    mine = api.prepare(draft).json()
    db.execute(text("RESET ROLE"))
    other_owner = make_account(db, "luis@example.com")
    as_role(db, PLATFORM_ROLE)

    def as_luis() -> CurrentUser:
        set_current_account(db, other_owner.id)
        return CurrentUser(other_owner.auth_user_id, other_owner.id, "luis@example.com", "", None)

    app.dependency_overrides[get_current_user] = as_luis

    assert api.prepare(Draft.of()).status_code == 404
    assert api.client.get(f"{api.doc_url}/saves/{mine['id']}").status_code == 404
    assert api.commit(mine["id"]).status_code == 404


def test_a_save_id_of_another_document_is_not_found(api: Api, db: Session) -> None:
    draft = Draft.of()
    save = api.prepare(draft).json()
    other = Document(
        workspace_id=api.workspace.id,
        name="Other",
        format="a4",
        width=1.0,
        height=1.0,
        source=api.document.source,
        status=DocumentStatus.DRAFT,
    )
    db.add(other)
    db.flush()

    assert (
        api.client.post(f"/api/v1/documents/{other.id}/saves/{save['id']}/commit").status_code
        == 404
    )


def test_without_storage_configured_the_save_routes_answer_503(api: Api) -> None:
    del app.dependency_overrides[object_store]
    assert not get_settings().s3_configured

    assert api.prepare(Draft.of()).status_code == 503
    assert api.count(DocumentSave) == 0
