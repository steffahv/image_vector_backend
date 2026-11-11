"""Published contracts of the documents and storage routes (VEC-31, VEC-42, VEC-43).

The routes answer 501 until their logic is written. These tests pin what the editor builds
against: every route is in Swagger, needs a session (except reading a shared document), accepts
a valid body and refuses input past its limits.
"""

import uuid
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.auth.service import CurrentUser, get_current_user
from app.core.config import get_settings
from app.main import app

DOC = f"/api/v1/documents/{uuid.uuid4()}"
SHA = "a" * 64

DOCUMENT_BODY = {"name": "Poster", "format": "a4", "width": 595, "height": 842}
SAVE_BODY: dict[str, Any] = {
    "idempotency_key": str(uuid.uuid4()),
    "base_revision": 0,
    "document": {
        "sha256": SHA,
        "size_bytes": 1000,
        "mime_type": "application/json",
        "original_bytes": 4000,
        "format_version": 1,
    },
    "images": [
        {
            "sha256": SHA,
            "size_bytes": 2000,
            "mime_type": "image/png",
            "editor_hash": "img-1",
            "width": 100,
            "height": 100,
        }
    ],
}

# (method, path, body) of every signed-in route, with a valid body.
SIGNED_IN_ROUTES: list[tuple[str, str, dict[str, Any] | None]] = [
    ("GET", "/api/v1/documents", None),
    ("POST", "/api/v1/documents", DOCUMENT_BODY),
    ("GET", DOC, None),
    ("PATCH", DOC, {"name": "Renamed"}),
    ("POST", f"{DOC}/duplicate", {}),
    ("POST", f"{DOC}/trash", None),
    ("POST", f"{DOC}/restore", None),
    ("POST", f"{DOC}/saves", SAVE_BODY),
    ("GET", f"{DOC}/saves/{uuid.uuid4()}", None),
    ("POST", f"{DOC}/saves/{uuid.uuid4()}/commit", None),
    ("GET", f"{DOC}/content", None),
    ("GET", f"{DOC}/versions", None),
    ("POST", f"{DOC}/versions", {"source": "manual", "label": "Before the client call"}),
    ("POST", f"{DOC}/versions/{uuid.uuid4()}/restore", {"base_revision": 3}),
    ("GET", "/api/v1/folders", None),
    ("POST", "/api/v1/folders", {"name": "Clients"}),
    ("PATCH", f"/api/v1/folders/{uuid.uuid4()}", {"name": "Old clients"}),
    ("DELETE", f"/api/v1/folders/{uuid.uuid4()}", None),
    ("POST", f"{DOC}/share-links", {"allows_download": False}),
    ("GET", f"{DOC}/share-links", None),
    ("DELETE", f"{DOC}/share-links/{uuid.uuid4()}", None),
    ("GET", "/api/v1/storage/quota", None),
]


@pytest.fixture
def client() -> TestClient:
    # https and the editor's Origin, as the browser sends them (origin check on writes).
    return TestClient(
        app,
        base_url="https://testserver",
        headers={"Origin": get_settings().frontend_url},
    )


@pytest.fixture
def signed_in() -> Iterator[None]:
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(
        user_id=uuid.uuid4(),
        account_id=uuid.uuid4(),
        email="ana@example.com",
        name="Ana",
        image_url=None,
    )
    try:
        yield
    finally:
        app.dependency_overrides.clear()


def _call(client: TestClient, method: str, path: str, body: dict[str, Any] | None) -> int:
    return client.request(method, path, json=body).status_code


@pytest.mark.parametrize(("method", "path", "body"), SIGNED_IN_ROUTES)
def test_every_route_needs_a_session(
    client: TestClient, method: str, path: str, body: dict[str, Any] | None
) -> None:
    assert _call(client, method, path, body) == 401


@pytest.mark.parametrize(("method", "path", "body"), SIGNED_IN_ROUTES)
def test_every_route_accepts_a_valid_request(
    client: TestClient,
    signed_in: None,
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    assert _call(client, method, path, body) == 501


def test_a_shared_document_is_read_without_a_session(client: TestClient) -> None:
    assert client.get("/api/v1/shared/some-token").status_code == 501


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/api/v1/documents", DOCUMENT_BODY | {"name": "x" * 201}),
        ("/api/v1/documents", DOCUMENT_BODY | {"width": 0}),
        ("/api/v1/documents", DOCUMENT_BODY | {"height": 1_000_000}),
        (f"{DOC}/saves", SAVE_BODY | {"base_revision": -1}),
        (f"{DOC}/saves", SAVE_BODY | {"images": SAVE_BODY["images"] * 501}),
        (
            f"{DOC}/saves",
            SAVE_BODY | {"document": SAVE_BODY["document"] | {"sha256": "not-a-hash"}},
        ),
        (
            f"{DOC}/saves",
            SAVE_BODY | {"document": SAVE_BODY["document"] | {"size_bytes": 51 * 1024 * 1024}},
        ),
        ("/api/v1/folders", {"name": ""}),
    ],
)
def test_input_past_its_limits_is_refused(
    client: TestClient, signed_in: None, path: str, body: dict[str, Any]
) -> None:
    assert client.post(path, json=body).status_code == 422


def test_every_route_is_in_swagger(client: TestClient) -> None:
    paths = client.get("/api/v1/openapi.json").json()["paths"]
    published = {(method.upper(), path) for path, item in paths.items() for method in item}
    for method, path, _ in SIGNED_IN_ROUTES:
        template = path.replace(DOC, "/api/v1/documents/{document_id}")
        assert any(m == method and _matches(template, p) for m, p in published), (
            f"{method} {path} is not in the OpenAPI schema"
        )
    assert ("GET", "/api/v1/shared/{token}") in published


def _matches(concrete: str, template: str) -> bool:
    concrete_parts, template_parts = concrete.split("/"), template.split("/")
    return len(concrete_parts) == len(template_parts) and all(
        c == t or t.startswith("{") for c, t in zip(concrete_parts, template_parts, strict=True)
    )
