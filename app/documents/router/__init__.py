"""HTTP routes for documents.

What goes here:
- Create, list, open and rename documents.
- Save a new revision (with base revision and idempotency key).
- Versions (list, create, restore), folders, trash and sharing.

Rules:
- Receive the request, validate it with schemas/ and call service/. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.

How to split: one file per group of routes, each with its own `APIRouter()`,
included below with `router.include_router(...)`. `app/health/router/` is an example.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/documents", tags=["documents"])
