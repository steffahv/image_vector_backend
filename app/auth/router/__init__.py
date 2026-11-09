"""HTTP routes for auth.

What goes here:
- email_links.py: ask for a one-time sign-in link.
- sessions.py: exchange a link for a session, read the signed-in user, sign out.
- google.py: Google sign-in and its callback.

Rules:
- Receive the request, validate it with schemas/ and call service/. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.
"""

from fastapi import APIRouter

from app.auth.router import email_links, google, sessions

router = APIRouter(prefix="/auth", tags=["auth"])
router.include_router(email_links.router)
router.include_router(sessions.router)
router.include_router(google.router)
