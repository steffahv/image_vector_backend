"""HTTP routes for storage.

What goes here:
- Request signed URLs to upload or download files.
- Confirm an upload so it can be checked.
- Read the current quota usage.

Rules:
- Receive the request, validate it with schemas/ and call service/. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.

How to split: one file per group of routes, each with its own `APIRouter()`,
included below with `router.include_router(...)`. `app/health/router/` is an example.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/storage", tags=["storage"])
