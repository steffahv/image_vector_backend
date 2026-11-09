"""Application entry point: creates the FastAPI app and registers every module's router."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.auth.router import router as auth_router
from app.auth.service import SessionCookieMiddleware
from app.billing.router import router as billing_router
from app.core.config import get_settings
from app.core.db import check_app_role, engine
from app.core.openapi import API_DESCRIPTION, API_TITLE, API_VERSION, TAGS_METADATA
from app.core.origin_check import OriginCheckMiddleware
from app.documents.router import router as documents_router
from app.health.router import router as health_router
from app.storage.router import router as storage_router

API_PREFIX = "/api/v1"

settings = get_settings()
docs_enabled = settings.api_docs_enabled


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    # In development a superuser is fine (docs/desarrollo.md); in staging and production the app
    # must not start with a database user that skips row-level security.
    if settings.app_env != "development":
        with engine.connect() as connection:
            check_app_role(connection)
    yield


app = FastAPI(
    lifespan=lifespan,
    title=API_TITLE,
    version=API_VERSION,
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    openapi_url=f"{API_PREFIX}/openapi.json" if docs_enabled else None,
    docs_url="/docs" if docs_enabled else None,
    redoc_url="/redoc" if docs_enabled else None,
)

app.add_middleware(SessionCookieMiddleware)
# Added last, so it runs first: preflight requests are answered before the origin check.
# The origin check runs before any route, so a refused request never reaches the database.
app.add_middleware(OriginCheckMiddleware, allowed_origins=settings.allowed_origins)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.frontend_url],
    # The editor sends the session cookie with `credentials: "include"`.
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type"],
)

for router in (health_router, auth_router, documents_router, storage_router, billing_router):
    app.include_router(router, prefix=API_PREFIX)
