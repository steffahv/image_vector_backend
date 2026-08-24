from fastapi import APIRouter

from app.models.health import HealthResponse
from app.services.health import get_health_status

api_router = APIRouter()


@api_router.get("/health", response_model=HealthResponse, tags=["health"])
def health_check() -> HealthResponse:
    return get_health_status()
