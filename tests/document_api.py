"""A signed-in test client for the documents routes, with an in-memory bucket.

Used by the save and open tests. The browser's upload is simulated by writing the bytes to the
key its signed URL points to.
"""

import gzip
import hashlib
import json
import uuid
from collections.abc import Iterator
from dataclasses import dataclass, field
from io import BytesIO
from typing import Any

from fastapi.testclient import TestClient
from httpx2 import Response
from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.service import CurrentUser, get_current_user
from app.core.config import get_settings
from app.core.db import PLATFORM_ROLE, get_db, set_current_account
from app.documents.models import Account, Document, Workspace
from app.documents.router.responses import object_store
from app.main import app
from app.storage.models import WorkspaceQuota
from tests.conftest import as_role
from tests.factories import make_account, make_document, make_quota, make_workspace
from tests.fake_storage import MemoryObjectStore

LIMIT = 10_000_000


def png(width: int = 4, height: int = 3, color: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    buffer = BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, "PNG")
    return buffer.getvalue()


def describe(data: bytes, mime_type: str, **extra: object) -> dict[str, Any]:
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data),
        "mime_type": mime_type,
    } | extra


@dataclass
class Draft:
    """A save request and the bytes the browser would upload for it."""

    document: bytes
    original_bytes: int
    thumbnail: bytes | None = None
    images: dict[str, bytes] = field(default_factory=dict)
    idempotency_key: uuid.UUID = field(default_factory=uuid.uuid4)

    @classmethod
    def of(
        cls, content: dict[str, Any] | None = None, images: dict[str, bytes] | None = None
    ) -> "Draft":
        text = json.dumps(content or {"pages": [{"id": "p1"}]}).encode()
        return cls(gzip.compress(text), len(text), png(8, 6), images or {"img-1": png()})

    def body(self, base_revision: int) -> dict[str, Any]:
        return {
            "idempotency_key": str(self.idempotency_key),
            "base_revision": base_revision,
            "document": describe(
                self.document,
                "application/json",
                gzip=True,
                original_bytes=self.original_bytes,
                format_version=1,
            ),
            "thumbnail": None
            if self.thumbnail is None
            else describe(self.thumbnail, "image/png", width=8, height=6),
            "images": [
                describe(
                    data, "image/png", editor_hash=name, width=_size(data)[0], height=_size(data)[1]
                )
                for name, data in self.images.items()
            ],
        }

    def bytes_for(self, target: dict[str, Any]) -> bytes:
        if target["role"] == "document":
            return self.document
        if target["role"] == "thumbnail":
            assert self.thumbnail is not None
            return self.thumbnail
        return self.images[target["editor_hash"]]


def _size(data: bytes) -> tuple[int, int]:
    with Image.open(BytesIO(data)) as image:
        return image.size


@dataclass
class Api:
    client: TestClient
    store: MemoryObjectStore
    db: Session
    account: Account
    workspace: Workspace
    document: Document

    @property
    def doc_url(self) -> str:
        return f"/api/v1/documents/{self.document.id}"

    def prepare(self, draft: Draft, base_revision: int = 0) -> Response:
        return self.client.post(f"{self.doc_url}/saves", json=draft.body(base_revision))

    def upload(self, draft: Draft, save: dict[str, Any], *, skip: str | None = None) -> None:
        """What the browser does with each signed URL."""
        for target in save["uploads"]:
            if target["role"] != skip:
                self.store.files[self.store.key_of(target["url"])] = draft.bytes_for(target)

    def commit(self, save_id: str) -> Response:
        return self.client.post(f"{self.doc_url}/saves/{save_id}/commit")

    def save(self, draft: Draft, base_revision: int = 0) -> Response:
        prepared = self.prepare(draft, base_revision)
        assert prepared.status_code == 201, prepared.text
        self.upload(draft, prepared.json())
        return self.commit(prepared.json()["id"])

    def quota(self) -> WorkspaceQuota:
        self.db.expire_all()
        return self.db.get_one(WorkspaceQuota, self.workspace.id)

    def current_revision(self) -> int | None:
        self.db.expire_all()
        return self.db.get_one(Document, self.document.id).current_revision

    def count(self, model: type, *conditions: Any) -> int:
        return self.db.scalar(select(func.count()).select_from(model).where(*conditions)) or 0


def signed_in_api(db: Session) -> Iterator[Api]:
    """Ana, her workspace with space and one draft document, signed in as the platform role."""
    account = make_account(db)
    workspace = make_workspace(db, account)
    make_quota(db, workspace, limit_bytes=LIMIT)
    document = make_document(db, workspace)
    store = MemoryObjectStore()
    as_role(db, PLATFORM_ROLE)

    def signed_in() -> CurrentUser:
        set_current_account(db, account.id)
        return CurrentUser(account.auth_user_id, account.id, "ana@example.com", "Ana", None)

    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = signed_in
    app.dependency_overrides[object_store] = lambda: store
    client = TestClient(
        app, base_url="https://testserver", headers={"Origin": get_settings().frontend_url}
    )
    try:
        yield Api(client, store, db, account, workspace, document)
    finally:
        app.dependency_overrides.clear()
