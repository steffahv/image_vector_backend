"""HTTP routes for billing.

What goes here:
- List plans, start a checkout and read the current subscription.
- Payment provider webhooks.

Rules:
- Receive the request, validate it with schemas.py and call service.py. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/billing", tags=["billing"])
