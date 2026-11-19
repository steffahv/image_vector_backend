"""Opening a document and restoring a version (VEC-42).

Opening hands out signed URLs only for the account's own documents, each for its one file and
for 10 minutes at most. Restoring publishes an old revision again as a new one: the number only
goes up and the previous head is kept so the restore can be undone.
"""

import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.auth.service import CurrentUser, get_current_user
from app.core.db import PLATFORM_ROLE, set_current_account
from app.documents.models import (
    Document,
    DocumentStatus,
    DocumentVersion,
    RevisionImage,
    VersionSource,
)
from app.main import app
from app.storage.models import ObjectStatus, StoredObject
from tests.conftest import as_role
from tests.document_api import Api, Draft, png
from tests.factories import make_account


def _open(api: Api) -> dict[str, object]:
    response = api.client.get(f"{api.doc_url}/content")
    assert response.status_code == 200, response.text
    body: dict[str, object] = response.json()
    return body


def _download(api: Api, url: str) -> bytes:
    """What the browser gets from a signed URL: the bytes of that one key."""
    return api.store.files[api.store.key_of(url)]


# Opening


def test_a_never_saved_draft_opens_empty_with_its_cache_scope(api: Api) -> None:
    content = _open(api)

    assert content == {
        "document_id": str(api.document.id),
        "workspace_id": str(api.workspace.id),
        "account_id": str(api.account.id),
        "revision": None,
        "document": None,
        "thumbnail": None,
        "images": [],
    }


def test_opening_signs_each_file_of_the_current_revision(api: Api) -> None:
    logo = png(5, 5, (0, 255, 0))
    draft = Draft.of(images={"logo": logo, "photo": png(6, 2)})
    api.save(draft)

    content = _open(api)

    assert content["revision"] == 1
    document = content["document"]
    assert isinstance(document, dict)
    assert _download(api, document["url"]) == draft.document
    assert document["sha256"] == hashlib.sha256(draft.document).hexdigest()
    assert (document["gzip"], document["format_version"]) == (True, 1)
    thumbnail = content["thumbnail"]
    assert isinstance(thumbnail, dict)
    assert _download(api, thumbnail["url"]) == draft.thumbnail
    images = content["images"]
    assert isinstance(images, list)
    assert {i["editor_hash"]: _download(api, i["url"]) for i in images} == draft.images


def test_signed_urls_last_ten_minutes_at_most(api: Api) -> None:
    api.save(Draft.of())

    content = _open(api)

    document = content["document"]
    assert isinstance(document, dict)
    expires_at = datetime.fromisoformat(document["expires_at"])
    assert expires_at <= datetime.now(UTC) + timedelta(minutes=10)
    ttl = int(parse_qs(urlparse(document["url"]).query)["ttl"][0])
    assert 0 < ttl <= 600


def test_another_accounts_document_is_not_found_and_gets_no_urls(api: Api, db: Session) -> None:
    api.save(Draft.of())
    db.execute(text("RESET ROLE"))
    luis = make_account(db, "luis@example.com")
    as_role(db, PLATFORM_ROLE)

    def as_luis() -> CurrentUser:
        set_current_account(db, luis.id)
        return CurrentUser(luis.auth_user_id, luis.id, "luis@example.com", "Luis", None)

    app.dependency_overrides[get_current_user] = as_luis
    response = api.client.get(f"{api.doc_url}/content")

    assert response.status_code == 404
    assert "url" not in response.text


def test_a_document_in_the_trash_is_not_opened(api: Api) -> None:
    api.save(Draft.of())
    api.db.execute(update(Document).values(status=DocumentStatus.TRASH))

    assert api.client.get(f"{api.doc_url}/content").status_code == 404


def test_a_document_whose_file_is_gone_answers_503_without_urls(api: Api) -> None:
    api.save(Draft.of())
    api.db.execute(update(StoredObject).values(status=ObjectStatus.DELETED))

    response = api.client.get(f"{api.doc_url}/content")

    assert response.status_code == 503
    assert "url" not in response.text


# Restoring


def _keep_version(api: Api, revision: int) -> uuid.UUID:
    version = DocumentVersion(
        workspace_id=api.workspace.id,
        document_id=api.document.id,
        revision=revision,
        source=VersionSource.MANUAL,
        label="Before the client call",
    )
    api.db.add(version)
    api.db.flush()
    return version.id


def _restore(api: Api, version_id: uuid.UUID, base_revision: int) -> dict[str, object]:
    response = api.client.post(
        f"{api.doc_url}/versions/{version_id}/restore", json={"base_revision": base_revision}
    )
    body: dict[str, object] = {"status": response.status_code} | response.json()
    return body


def test_restoring_publishes_the_old_revision_as_a_new_one(api: Api) -> None:
    first = Draft.of({"pages": ["first"]}, images={"logo": png(5, 5)})
    api.save(first)
    version_id = _keep_version(api, 1)
    api.save(Draft.of({"pages": ["second"]}, images={"photo": png(7, 7)}), base_revision=1)

    restored = _restore(api, version_id, base_revision=2)

    assert (restored["status"], restored["revision"]) == (200, 3)
    assert api.current_revision() == 3
    content = _open(api)
    document = content["document"]
    assert isinstance(document, dict)
    assert _download(api, document["url"]) == first.document
    maps = api.db.scalars(select(RevisionImage.editor_hash).where(RevisionImage.revision == 3))
    assert list(maps) == ["logo"]
    undo = api.db.get_one(DocumentVersion, uuid.UUID(str(restored["undo_version_id"])))
    assert (undo.revision, undo.source) == (2, VersionSource.RESTORE)


def test_restoring_twice_never_brings_an_old_number_back(api: Api) -> None:
    api.save(Draft.of())
    version_id = _keep_version(api, 1)
    api.save(Draft.of({"pages": []}), base_revision=1)

    first = _restore(api, version_id, base_revision=2)
    undo = _restore(api, uuid.UUID(str(first["undo_version_id"])), base_revision=3)

    assert (first["revision"], undo["revision"]) == (3, 4)
    assert api.current_revision() == 4


def test_restoring_from_a_stale_screen_conflicts_and_changes_nothing(api: Api) -> None:
    api.save(Draft.of())
    version_id = _keep_version(api, 1)
    api.save(Draft.of({"pages": []}), base_revision=1)

    conflict = _restore(api, version_id, base_revision=1)

    assert (conflict["status"], conflict["current_revision"]) == (409, 2)
    assert api.current_revision() == 2
    assert (
        api.db.scalar(
            select(DocumentVersion.id).where(DocumentVersion.source == VersionSource.RESTORE)
        )
        is None
    )


def test_a_version_of_another_document_is_not_found(api: Api, db: Session) -> None:
    api.save(Draft.of())
    version_id = _keep_version(api, 1)
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

    response = api.client.post(
        f"/api/v1/documents/{other.id}/versions/{version_id}/restore", json={"base_revision": 1}
    )

    assert response.status_code == 404
    assert api.current_revision() == 1
