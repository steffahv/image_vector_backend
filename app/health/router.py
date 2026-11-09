"""HTTP routes for health. Only receives the request and calls the service."""

from fastapi import APIRouter

from app.health.schemas import HealthResponse
from app.health.service import get_health_status

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, summary="Check that the service is up")
def health_check() -> HealthResponse:
    return get_health_status()
