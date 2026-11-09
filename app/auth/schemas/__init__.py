"""Pydantic request and response models for the auth API.

What goes here: sign-in bodies, session and current-user responses.
Never return password hashes or tokens: the session token only travels in its cookie.

One file per topic:
- email_link.py: asking for a sign-in link and previewing who it is for.
- session.py: exchanging a link for a session, and the signed-in user.
"""

from app.auth.schemas.email_link import (
    EmailLinkCreate,
    EmailLinkPreviewResponse,
    EmailLinkResponse,
    EmailLinkToken,
)
from app.auth.schemas.session import CurrentUserResponse, SessionCreate

__all__ = [
    "CurrentUserResponse",
    "EmailLinkCreate",
    "EmailLinkPreviewResponse",
    "EmailLinkResponse",
    "EmailLinkToken",
    "SessionCreate",
]
