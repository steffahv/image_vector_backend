"""HTTP routes for auth.

What goes here:
- Sign up, sign in and sign out with email.
- Google sign-in and its callback.
- Reading the current session.
Exact routes depend on the identity library (VEC-40).

Rules:
- Receive the request, validate it with schemas/ and call service/. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.

How to split: one file per group of routes, each with its own `APIRouter()`,
included below with `router.include_router(...)`. `app/health/router/` is an example.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/auth", tags=["auth"])
