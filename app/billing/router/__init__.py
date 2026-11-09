"""HTTP routes for billing.

What goes here:
- List plans, start a checkout and read the current subscription.
- Payment provider webhooks.

Rules:
- Receive the request, validate it with schemas/ and call service/. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.

How to split: one file per group of routes, each with its own `APIRouter()`,
included below with `router.include_router(...)`. `app/health/router/` is an example.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/billing", tags=["billing"])
