"""Business logic for auth.

What goes here:
- Sign-in with a one-time email link or with Google, sessions and sign-out.
- `get_current_user`, the dependency other modules use to know who is calling.

Other modules use auth only through this file, never by reading its tables.

One file per use case:
- email_links.py: request, preview and consume sign-in links, with the per-email limit.
- google.py: the OAuth round trip with Google (Authlib).
- sign_in.py: proven identity -> user, account and session.
- users.py: find or create the auth user once its email is proven.
- sessions.py: start, find, rotate and end sessions (one, or all of a user's).
- current_user.py: `get_current_user` and `CurrentUser`.
- cookies.py: the session cookie and the Google round-trip cookie.
- email_delivery.py: sending links (console in development until a provider is chosen).
- tokens.py: random tokens and their SHA-256 hash.
- errors.py: auth errors, turned into HTTP responses by the router.
"""

from app.auth.service.cookies import (
    GOOGLE_COOKIE,
    SESSION_COOKIE,
    SessionCookieMiddleware,
    clear_google_cookie,
    clear_session_cookie,
    read_google_cookie,
    set_google_cookie,
    set_session_cookie,
)
from app.auth.service.current_user import CurrentUser, get_current_user, session_cookie
from app.auth.service.email_delivery import EmailSender, get_email_sender
from app.auth.service.email_links import preview_sign_in_link, request_sign_in_link
from app.auth.service.errors import (
    AuthError,
    EmailDeliveryUnavailable,
    GoogleSignInFailed,
    GoogleSignInUnavailable,
    InvalidEmailLink,
    TooManyEmailLinks,
)
from app.auth.service.google import (
    GOOGLE_CALLBACK_PATH,
    GoogleAuthorization,
    GoogleClient,
    GoogleProfile,
    get_google_client,
)
from app.auth.service.sessions import sign_out, sign_out_everywhere
from app.auth.service.sign_in import SignedIn, sign_in_with_email_link, sign_in_with_google
from app.auth.service.tokens import TOKEN_PATTERN

__all__ = [
    "GOOGLE_CALLBACK_PATH",
    "GOOGLE_COOKIE",
    "SESSION_COOKIE",
    "TOKEN_PATTERN",
    "AuthError",
    "CurrentUser",
    "EmailDeliveryUnavailable",
    "EmailSender",
    "GoogleAuthorization",
    "GoogleClient",
    "GoogleProfile",
    "GoogleSignInFailed",
    "GoogleSignInUnavailable",
    "InvalidEmailLink",
    "SessionCookieMiddleware",
    "SignedIn",
    "TooManyEmailLinks",
    "clear_google_cookie",
    "clear_session_cookie",
    "get_current_user",
    "get_email_sender",
    "get_google_client",
    "read_google_cookie",
    "preview_sign_in_link",
    "request_sign_in_link",
    "session_cookie",
    "sign_out",
    "sign_out_everywhere",
    "set_google_cookie",
    "set_session_cookie",
    "sign_in_with_email_link",
    "sign_in_with_google",
]
