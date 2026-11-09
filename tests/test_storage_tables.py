"""Database rules of revision images, share links, saves, uploads, quotas and reservations."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.documents.models import Document, RevisionImage, ShareLink, Workspace
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
from tests.factories import make_document, make_object, make_revision, make_workspace


def _in_one_hour() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def _share_link(db: Session, document: Document, token: str = "token") -> ShareLink:
    link = ShareLink(
        workspace_id=document.workspace_id,
        document_id=document.id,
        token_hash=hashlib.sha256(token.encode()).digest(),
        active=True,
        allows_download=False,
    )
    db.add(link)
    db.flush()
    return link


def _save(db: Session, document: Document, **overrides: object) -> DocumentSave:
    owner_id = db.get(Workspace, document.workspace_id).owner_id  # type: ignore[union-attr]
    values: dict[str, object] = {
        "workspace_id": document.workspace_id,
        "document_id": document.id,
        "account_id": owner_id,
        "idempotency_key": uuid.uuid4(),
        "request_fingerprint": b"fingerprint",
        "base_revision": 0,
        "status": SaveStatus.PREPARING,
        "expires_at": _in_one_hour(),
    }
    save = DocumentSave(**(values | overrides))
    db.add(save)
    db.flush()
    return save


def _upload(db: Session, workspace: Workspace, **overrides: object) -> Upload:
    values: dict[str, object] = {
        "workspace_id": workspace.id,
        "account_id": workspace.owner_id,
        "kind": ObjectKind.IMAGE,
        "temp_key": f"tmp/{uuid.uuid4()}",
        "max_bytes": 1024,
        "status": UploadStatus.PENDING,
        "expires_at": _in_one_hour(),
    }
    upload = Upload(**(values | overrides))
    db.add(upload)
    db.flush()
    return upload


def _quota(db: Session, workspace: Workspace, **overrides: int) -> WorkspaceQuota:
    values = {"limit_bytes": 1000, "used_bytes": 0, "reserved_bytes": 0} | overrides
    quota = WorkspaceQuota(workspace_id=workspace.id, **values)
    db.add(quota)
    db.flush()
    return quota


def test_same_image_can_be_used_by_several_revisions(db: Session) -> None:
    workspace = make_workspace(db)
    document = make_document(db, workspace)
    json_object = make_object(db, workspace)
    image = make_object(db, workspace, ObjectKind.IMAGE)
    for number in (1, 2):
        make_revision(db, document, json_object, revision=number)
        db.add(
            RevisionImage(
                workspace_id=workspace.id,
                document_id=document.id,
                revision=number,
                editor_hash="img-1",
                image_object_id=image.id,
            )
        )
    db.flush()


def test_revision_image_must_be_in_the_same_workspace(db: Session) -> None:
    workspace = make_workspace(db)
    document = make_document(db, workspace)
    make_revision(db, document, make_object(db, workspace))
    foreign_image = make_object(db, make_workspace(db), ObjectKind.IMAGE)

    db.add(
        RevisionImage(
            workspace_id=workspace.id,
            document_id=document.id,
            revision=1,
            editor_hash="img-1",
            image_object_id=foreign_image.id,
        )
    )
    with pytest.raises(IntegrityError, match="fk_revision_images_workspace_id_image_object_id"):
        db.flush()


def test_share_link_token_hash_is_sha256_and_unique(db: Session) -> None:
    document = make_document(db, make_workspace(db))
    _share_link(db, document, "same")

    with pytest.raises(IntegrityError, match="uq_share_links_token_hash"):
        with db.begin_nested():
            _share_link(db, document, "same")

    db.add(
        ShareLink(
            workspace_id=document.workspace_id,
            document_id=document.id,
            token_hash=b"short",
            active=True,
            allows_download=False,
        )
    )
    with pytest.raises(IntegrityError, match="ck_share_links_token_hash_sha256"):
        db.flush()


def test_retried_save_with_the_same_key_is_rejected(db: Session) -> None:
    document = make_document(db, make_workspace(db))
    key = uuid.uuid4()
    _save(db, document, idempotency_key=key)

    with pytest.raises(IntegrityError, match="uq_saves_document_id_idempotency_key"):
        _save(db, document, idempotency_key=key)


def test_upload_save_must_be_in_the_same_workspace(db: Session) -> None:
    foreign_save = _save(db, make_document(db, make_workspace(db)))

    with pytest.raises(IntegrityError, match="fk_uploads_workspace_id_save_id_saves"):
        _upload(db, make_workspace(db), save_id=foreign_save.id)


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("max_bytes", 0, "ck_uploads_max_bytes_positive"),
        ("declared_sha256", b"short", "ck_uploads_declared_sha256_length"),
    ],
)
def test_upload_values_are_checked(db: Session, field: str, value: object, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        _upload(db, make_workspace(db), **{field: value})


def test_workspace_can_go_over_its_limit_but_not_below_zero(db: Session) -> None:
    # After a plan downgrade, usage above the limit must still be storable.
    _quota(db, make_workspace(db), limit_bytes=100, used_bytes=500)

    with pytest.raises(IntegrityError, match="ck_workspace_quotas_used_bytes_non_negative"):
        _quota(db, make_workspace(db), used_bytes=-1)


def test_an_upload_holds_space_only_once(db: Session) -> None:
    workspace = make_workspace(db)
    _quota(db, workspace)
    upload = _upload(db, workspace)

    def reserve(amount: int) -> None:
        db.add(
            ByteReservation(
                workspace_id=workspace.id,
                upload_id=upload.id,
                amount=amount,
                status=ByteReservationStatus.RESERVED,
                expires_at=_in_one_hour(),
            )
        )
        db.flush()

    with pytest.raises(IntegrityError, match="ck_byte_reservations_amount_positive"):
        with db.begin_nested():
            reserve(0)

    reserve(100)
    with pytest.raises(IntegrityError, match="uq_byte_reservations_upload_id"):
        reserve(100)


def test_reservation_needs_the_workspace_quota(db: Session) -> None:
    workspace = make_workspace(db)
    upload = _upload(db, workspace)

    db.add(
        ByteReservation(
            workspace_id=workspace.id,
            upload_id=upload.id,
            amount=10,
            status=ByteReservationStatus.RESERVED,
            expires_at=_in_one_hour(),
        )
    )
    with pytest.raises(IntegrityError, match="fk_byte_reservations_workspace_id_workspace_quotas"):
        db.flush()
