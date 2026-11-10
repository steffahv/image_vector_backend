"""Database rules of revision images, share links, saves, uploads, quotas and reservations."""

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.documents.models import RevisionImage, ShareLink
from app.storage.models import (
    ByteReservation,
    ByteReservationStatus,
    ObjectKind,
)
from tests.factories import (
    in_one_hour,
    make_document,
    make_object,
    make_quota,
    make_revision,
    make_save,
    make_share_link,
    make_upload,
    make_workspace,
)


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
    make_share_link(db, document, "same")

    with pytest.raises(IntegrityError, match="uq_share_links_token_hash"):
        with db.begin_nested():
            make_share_link(db, document, "same")

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
    make_save(db, document, idempotency_key=key)

    with pytest.raises(IntegrityError, match="uq_saves_document_id_idempotency_key"):
        make_save(db, document, idempotency_key=key)


def test_upload_save_must_be_in_the_same_workspace(db: Session) -> None:
    foreign_save = make_save(db, make_document(db, make_workspace(db)))

    with pytest.raises(IntegrityError, match="fk_uploads_workspace_id_save_id_saves"):
        make_upload(db, make_workspace(db), save_id=foreign_save.id)


@pytest.mark.parametrize(
    ("field", "value", "constraint"),
    [
        ("max_bytes", 0, "ck_uploads_max_bytes_positive"),
        ("declared_sha256", b"short", "ck_uploads_declared_sha256_length"),
    ],
)
def test_upload_values_are_checked(db: Session, field: str, value: object, constraint: str) -> None:
    with pytest.raises(IntegrityError, match=constraint):
        make_upload(db, make_workspace(db), **{field: value})


def test_workspace_can_go_over_its_limit_but_not_below_zero(db: Session) -> None:
    # After a plan downgrade, usage above the limit must still be storable.
    make_quota(db, make_workspace(db), limit_bytes=100, used_bytes=500)

    with pytest.raises(IntegrityError, match="ck_workspace_quotas_used_bytes_non_negative"):
        make_quota(db, make_workspace(db), used_bytes=-1)


def test_an_upload_holds_space_only_once(db: Session) -> None:
    workspace = make_workspace(db)
    make_quota(db, workspace)
    upload = make_upload(db, workspace)

    def reserve(amount: int) -> None:
        db.add(
            ByteReservation(
                workspace_id=workspace.id,
                upload_id=upload.id,
                amount=amount,
                status=ByteReservationStatus.RESERVED,
                expires_at=in_one_hour(),
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
    upload = make_upload(db, workspace)

    db.add(
        ByteReservation(
            workspace_id=workspace.id,
            upload_id=upload.id,
            amount=10,
            status=ByteReservationStatus.RESERVED,
            expires_at=in_one_hour(),
        )
    )
    with pytest.raises(IntegrityError, match="fk_byte_reservations_workspace_id_workspace_quotas"):
        db.flush()
