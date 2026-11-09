"""Refuses requests that change data unless they come from one of our own origins (CSRF).

The session travels in a cookie, which the browser attaches to any request to the API, also one
started by another site. Browsers always send `Origin` on POST, PUT, PATCH and DELETE, and a page
cannot fake it, so requiring one of our origins stops another site from acting with the user's
session. `SameSite=Lax` on the cookie is the second barrier.

A request with no `Origin` is refused too: only non-browser clients omit it, and those can send
the header themselves.
"""

from starlette.datastructures import Headers
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class OriginCheckMiddleware:
    def __init__(self, app: ASGIApp, allowed_origins: frozenset[str]) -> None:
        self.app = app
        self.allowed_origins = allowed_origins

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope["method"] in UNSAFE_METHODS:
            origin = Headers(scope=scope).get("origin")
            if origin not in self.allowed_origins:
                response = JSONResponse({"detail": "Request refused."}, status_code=403)
                await response(scope, receive, send)
                return
        await self.app(scope, receive, send)
