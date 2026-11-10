"""Builders for test rows. Each one inserts and flushes, so ids and defaults are filled."""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.auth.models import AuthUser
from app.documents.models import (
    Account,
    AgentMode,
    Document,
    DocumentRevision,
    DocumentSource,
    DocumentStatus,
    RevisionAuthorType,
    ShareLink,
    Workspace,
    WorkspaceType,
)
from app.storage.models import (
    DocumentSave,
    ObjectEncoding,
    ObjectKind,
    ObjectStatus,
    SaveStatus,
    StoredObject,
    Upload,
    UploadStatus,
    WorkspaceQuota,
)


def make_account(db: Session, email: str = "ana@example.com") -> Account:
    user = AuthUser(email=email)
    db.add(user)
    db.flush()
    account = Account(
        auth_user_id=user.id, name="Ana", language="es", agent_mode=AgentMode.PLATFORM
    )
    db.add(account)
    db.flush()
    return account


def make_workspace(db: Session, account: Account | None = None) -> Workspace:
    owner = account or make_account(db, f"{uuid.uuid4().hex}@example.com")
    workspace = Workspace(owner_id=owner.id, name="Personal", type=WorkspaceType.PERSONAL)
    db.add(workspace)
    db.flush()
    return workspace


def make_object(
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


def make_document(db: Session, workspace: Workspace, **overrides: object) -> Document:
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


def make_revision(
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


def in_one_hour() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def make_share_link(db: Session, document: Document, token: str = "token") -> ShareLink:
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


def make_save(db: Session, document: Document, **overrides: object) -> DocumentSave:
    owner_id = db.get(Workspace, document.workspace_id).owner_id  # type: ignore[union-attr]
    values: dict[str, object] = {
        "workspace_id": document.workspace_id,
        "document_id": document.id,
        "account_id": owner_id,
        "idempotency_key": uuid.uuid4(),
        "request_fingerprint": b"fingerprint",
        "base_revision": 0,
        "status": SaveStatus.PREPARING,
        "expires_at": in_one_hour(),
    }
    save = DocumentSave(**(values | overrides))
    db.add(save)
    db.flush()
    return save


def make_upload(db: Session, workspace: Workspace, **overrides: object) -> Upload:
    values: dict[str, object] = {
        "workspace_id": workspace.id,
        "account_id": workspace.owner_id,
        "kind": ObjectKind.IMAGE,
        "temp_key": f"tmp/{uuid.uuid4()}",
        "max_bytes": 1024,
        "status": UploadStatus.PENDING,
        "expires_at": in_one_hour(),
    }
    upload = Upload(**(values | overrides))
    db.add(upload)
    db.flush()
    return upload


def make_quota(db: Session, workspace: Workspace, **overrides: int) -> WorkspaceQuota:
    values = {"limit_bytes": 1000, "used_bytes": 0, "reserved_bytes": 0} | overrides
    quota = WorkspaceQuota(workspace_id=workspace.id, **values)
    db.add(quota)
    db.flush()
    return quota
