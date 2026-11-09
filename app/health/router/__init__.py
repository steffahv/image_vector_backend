"""HTTP routes for health. One file per group of routes, included here."""

from fastapi import APIRouter

from app.health.router import health_check

router = APIRouter(tags=["health"])
router.include_router(health_check.router)
