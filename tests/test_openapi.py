from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_swagger_and_openapi_are_served() -> None:
    assert client.get("/docs").status_code == 200

    schema = client.get("/api/v1/openapi.json").json()
    tag_names = {tag["name"] for tag in schema["tags"]}
    assert {"health", "auth", "documents", "storage", "billing"} <= tag_names
    assert "/api/v1/health" in schema["paths"]
