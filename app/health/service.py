"""Health logic. Kept separate from the router so it can grow (e.g. a database ping)."""

from app.health.schemas import HealthResponse


def get_health_status() -> HealthResponse:
    return HealthResponse(status="ok", service="image-vector-backend")
