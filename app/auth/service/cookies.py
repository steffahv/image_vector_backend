"""The session cookie and the short-lived cookie of the Google round trip.

Both are HttpOnly (page scripts cannot read them), Secure (only sent over HTTPS; browsers accept
it on http://localhost too) and SameSite=Lax (not sent on requests started by other sites,
except plain link navigation, which Google's redirect back needs).
"""

import hmac

from fastapi import Request, Response
from starlette.datastructures import MutableHeaders
from starlette.responses import PlainTextResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.auth.service.errors import GoogleSignInFailed
from app.auth.service.sessions import SESSION_TTL
from app.core.config import get_settings

SESSION_COOKIE = "vectoredit_session"
# Holds the OAuth `state` and the PKCE verifier between leaving for Google and coming back.
GOOGLE_COOKIE = "vectoredit_google"
GOOGLE_COOKIE_TTL_SECONDS = 600
# Scope key where get_current_user leaves a rotated token for SessionCookieMiddleware.
_ROTATED_TOKEN_KEY = "vectoredit.rotated_session_token"


def set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
        domain=get_settings().session_cookie_domain,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(
        SESSION_COOKIE,
        domain=get_settings().session_cookie_domain,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def set_google_cookie(response: Response, state: str, code_verifier: str) -> None:
    response.set_cookie(
        GOOGLE_COOKIE,
        f"{state}.{code_verifier}",
        max_age=GOOGLE_COOKIE_TTL_SECONDS,
        httponly=True,
        secure=True,
        samesite="lax",
    )


def clear_google_cookie(response: Response) -> None:
    response.delete_cookie(GOOGLE_COOKIE, httponly=True, secure=True, samesite="lax")


def read_google_cookie(cookie: str | None, state: str | None) -> str:
    """The PKCE verifier, if the `state` Google sent back is the one this browser left with.

    A mismatch means the callback was not started by this browser: someone trying to sign the
    user in to another account (login CSRF), or a replayed callback.
    """
    expected_state, _, code_verifier = (cookie or "").partition(".")
    if not (state and expected_state and code_verifier):
        raise GoogleSignInFailed
    # Bytes: compare_digest refuses non-ASCII str, and `state` comes from the query string.
    if not hmac.compare_digest(state.encode(), expected_state.encode()):
        raise GoogleSignInFailed
    return code_verifier


class SessionCookieMiddleware:
    """Sends a rotated session token with whatever response the request ends up with.

    A cookie set on the `response` parameter of a dependency is dropped when the route raises
    (a 404, a 403...) or returns its own Response. After a rotation the database already holds
    the new token, so losing its cookie would leave the browser with the old one and sign the
    user out once the grace period ends. An unhandled error (500) is answered here, with the
    cookie, and raised again so it is still logged as usual.
    A response that sets or clears the session cookie itself (sign-out) is left as it is.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        rotated: dict[str, str] = {}
        scope[_ROTATED_TOKEN_KEY] = rotated
        started = False

        async def send_with_cookie(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
                if "token" in rotated:
                    headers = MutableHeaders(scope=message)
                    cookies = headers.getlist("set-cookie")
                    if not any(cookie.startswith(f"{SESSION_COOKIE}=") for cookie in cookies):
                        headers.append("set-cookie", _session_cookie_header(rotated["token"]))
            await send(message)

        try:
            await self.app(scope, receive, send_with_cookie)
        except Exception:
            # Starlette's error handler answers 500 outside this middleware, without the cookie.
            # Answer it here instead; seeing the response started, that handler only re-raises.
            if "token" in rotated and not started:
                error = PlainTextResponse("Internal Server Error", status_code=500)
                await error(scope, receive, send_with_cookie)
            raise


def send_rotated_token(request: Request, token: str) -> None:
    """Have SessionCookieMiddleware send this new session token with the response."""
    rotated = request.scope.get(_ROTATED_TOKEN_KEY)
    if rotated is None:
        raise RuntimeError("SessionCookieMiddleware is not installed")
    rotated["token"] = token


def _session_cookie_header(token: str) -> str:
    # Built by set_session_cookie, so the attributes are always the same as at sign-in.
    response = Response()
    set_session_cookie(response, token)
    return response.headers["set-cookie"]
