"""Application entry point: creates the FastAPI app and registers every module's router."""

from fastapi import FastAPI

from app.auth.router import router as auth_router
from app.billing.router import router as billing_router
from app.core.config import get_settings
from app.core.openapi import API_DESCRIPTION, API_TITLE, API_VERSION, TAGS_METADATA
from app.documents.router import router as documents_router
from app.health.router import router as health_router
from app.storage.router import router as storage_router

API_PREFIX = "/api/v1"

settings = get_settings()
docs_enabled = settings.api_docs_enabled

app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
)

for router in (health_router, auth_router, documents_router, storage_router, billing_router):
    app.include_router(router, prefix=API_PREFIX)
