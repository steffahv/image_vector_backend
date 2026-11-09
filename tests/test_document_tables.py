"""Database rules of workspaces, folders, documents, revisions, versions and objects."""

import hashlib
import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import AuthUser
from app.documents.models import (
    Account,
    AgentMode,
    Document,
    DocumentRevision,
    DocumentSource,
    DocumentStatus,
    DocumentVersion,
    Folder,
    RevisionAuthorType,
    VersionSource,
    Workspace,
    WorkspaceType,
)
from app.storage.models import ObjectEncoding, ObjectKind, ObjectStatus, StoredObject


def _account(db: Session, email: str = "ana@example.com") -> Account:
    user = AuthUser(email=email)
    db.add(user)
    db.flush()
    account = Account(
        auth_user_id=user.id, name="Ana", language="es", agent_mode=AgentMode.PLATFORM
    )
    db.add(account)
    db.flush()
    return account


def _workspace(db: Session, account: Account | None = None) -> Workspace:
    owner = account or _account(db, f"{uuid.uuid4().hex}@example.com")
    workspace = Workspace(owner_id=owner.id, name="Personal", type=WorkspaceType.PERSONAL)
    db.add(workspace)
    db.flush()
    return workspace


def _object(
    db: Session,
    workspace: Workspace,
    kind: ObjectKind = ObjectKind.DOCUMENT_JSON,
    content: bytes | None = None,
    **overrides: object,
) -> StoredObject:
    data = content if content is not None else uuid.uuid4().bytes
    values: dict[str, object] = {
        "workspace_id": workspace.id,
        "kind": kind,
        "bucket": "documents",
        "key": f"{workspace.id}/{uuid.uuid4()}",
        "sha256": hashlib.sha256(data).digest(),
        "size_bytes": len(data),
        "mime_type": "application/json",
        "encoding": ObjectEncoding.IDENTITY,
        "status": ObjectStatus.READY,
        "verified_at": datetime.now(UTC),
    }
    stored = StoredObject(**(values | overrides))
    db.add(stored)
    db.flush()
    return stored


def _document(db: Session, workspace: Workspace, **overrides: object) -> Document:
    values: dict[str, object] = {
        "workspace_id": workspace.id,
        "name": "Poster",
        "format": "a4",
        "width": 595.0,
        "height": 842.0,
        "source": DocumentSource.BLANK,
        "status": DocumentStatus.DRAFT,
    }
    document = Document(**(values | overrides))
    db.add(document)
    db.flush()
    return document


def _revision(
    db: Session, document: Document, json_object: StoredObject, revision: int = 1
) -> DocumentRevision:
    saved = DocumentRevision(
        workspace_id=document.workspace_id,
        document_id=document.id,
        revision=revision,
        json_object_id=json_object.id,
        format_version=1,
        original_json_bytes=json_object.size_bytes,
        author_type=RevisionAuthorType.ACCOUNT,
    )
    db.add(saved)
    db.flush()
    return saved


def _check_deferred_keys(db: Session) -> None:
    """Deferred keys are checked at commit; tests roll back, so force the check now."""
    db.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))


def test_an_account_has_only_one_personal_workspace(db: Session) -> None:
    account = _account(db)
    _workspace(db, account)
    db.add(Workspace(owner_id=account.id, name="Another", type=WorkspaceType.PERSONAL))
    with pytest.raises(IntegrityError, match="uq_workspaces_owner_id_personal"):
        db.flush()


def test_folder_parent_must_be_in_the_same_workspace(db: Session) -> None:
    parent = Folder(workspace_id=_workspace(db).id, name="Clients")
    db.add(parent)
    db.flush()

    db.add(Folder(workspace_id=_workspace(db).id, parent_id=parent.id, name="Other space"))
    with pytest.raises(IntegrityError, match="fk_folders_workspace_id_parent_id_folders"):
        db.flush()


def test_folder_cannot_be_its_own_parent(db: Session) -> None:
    folder = Folder(workspace_id=_workspace(db).id, name="Loop")
    db.add(folder)
    db.flush()

    folder.parent_id = folder.id
    with pytest.raises(IntegrityError, match="ck_folders_not_own_parent"):
        db.flush()


def test_document_folder_must_be_in_the_same_workspace(db: Session) -> None:
    folder = Folder(workspace_id=_workspace(db).id, name="Clients")
    db.add(folder)
    db.flush()

    with pytest.raises(IntegrityError, match="fk_documents_workspace_id_folder_id_folders"):
        _document(db, _workspace(db), folder_id=folder.id)


@pytest.mark.parametrize("width", [0.0, -1.0, float("inf"), float("nan")])
def test_document_dimensions_must_be_positive_and_finite(db: Session, width: float) -> None:
    with pytest.raises(IntegrityError, match="ck_documents_dimensions_positive_finite"):
        _document(db, _workspace(db), width=width)


def test_only_drafts_may_have_no_current_revision(db: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_documents_current_revision_required"):
        _document(db, _workspace(db), status=DocumentStatus.ACTIVE)


def test_document_and_its_first_revision_are_saved_together(db: Session) -> None:
    workspace = _workspace(db)
    document = _document(db, workspace)
    _revision(db, document, _object(db, workspace))

    document.status = DocumentStatus.ACTIVE
    document.current_revision = 1
    db.flush()
    _check_deferred_keys(db)


def test_current_revision_must_exist(db: Session) -> None:
    document = _document(db, _workspace(db), status=DocumentStatus.ACTIVE, current_revision=7)
    assert document.current_revision == 7

    with pytest.raises(IntegrityError, match="fk_documents_current_revision_document_revisions"):
        _check_deferred_keys(db)


def test_revision_files_must_be_in_the_same_workspace(db: Session) -> None:
    document = _document(db, _workspace(db))
    foreign_file = _object(db, _workspace(db))

    with pytest.raises(
        IntegrityError, match="fk_document_revisions_workspace_id_json_object_id_objects"
    ):
        _revision(db, document, foreign_file)


def test_revision_numbers_are_positive_and_unique_per_document(db: Session) -> None:
    workspace = _workspace(db)
    document = _document(db, workspace)
    json_object = _object(db, workspace)

    with pytest.raises(IntegrityError, match="ck_document_revisions_revision_positive"):
        with db.begin_nested():
            _revision(db, document, json_object, revision=0)

    _revision(db, document, json_object, revision=1)
    with pytest.raises(IntegrityError, match="pk_document_revisions"):
        _revision(db, document, json_object, revision=1)


def test_version_must_point_to_an_existing_revision(db: Session) -> None:
    workspace = _workspace(db)
    document = _document(db, workspace)
    _revision(db, document, _object(db, workspace))

    kept = DocumentVersion(
        workspace_id=workspace.id, document_id=document.id, revision=1, source=VersionSource.MANUAL
    )
    db.add(kept)
    db.flush()

    db.add(
        DocumentVersion(
            workspace_id=workspace.id,
            document_id=document.id,
            revision=2,
            source=VersionSource.PRE_AGENT,
        )
    )
    with pytest.raises(IntegrityError, match="fk_document_versions_revision_document_revisions"):
        db.flush()


def test_object_hash_must_be_sha256(db: Session) -> None:
    with pytest.raises(IntegrityError, match="ck_objects_sha256_length"):
        _object(db, _workspace(db), sha256=b"short")


def test_ready_images_are_stored_once_per_workspace(db: Session) -> None:
    workspace = _workspace(db)
    _object(db, workspace, ObjectKind.IMAGE, content=b"same image")

    # Another workspace may keep its own copy of the same image.
    _object(db, _workspace(db), ObjectKind.IMAGE, content=b"same image")

    with pytest.raises(IntegrityError, match="uq_objects_workspace_id_sha256_ready_image"):
        _object(db, workspace, ObjectKind.IMAGE, content=b"same image")


def test_non_image_files_may_repeat_content(db: Session) -> None:
    workspace = _workspace(db)
    _object(db, workspace, ObjectKind.DOCUMENT_JSON, content=b"{}")
    _object(db, workspace, ObjectKind.DOCUMENT_JSON, content=b"{}")
