"""HTTP routes for auth.

What goes here:
- POST /auth/sign-up, POST /auth/sign-in, POST /auth/sign-out.
- GET /auth/google and its callback.
- GET /auth/session: who is signed in.

Rules:
- Receive the request, validate it with schemas.py and call service.py. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
