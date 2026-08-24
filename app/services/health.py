from app.models.health import HealthResponse


def get_health_status() -> HealthResponse:
    return HealthResponse(status="ok", service="image-vector-backend")
