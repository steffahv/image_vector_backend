"""Google sign-in.

The callback is a GET that creates a session: an accepted exception to "no GET changes data"
(AGENTS.md), because Google sends the user back with a redirect. What protects it is the one-time
`state` and PKCE verifier kept in a cookie of this browser, checked before anything is created.
"""

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from app.auth.service import (
    GOOGLE_COOKIE,
    GoogleClient,
    GoogleSignInFailed,
    GoogleSignInUnavailable,
    clear_google_cookie,
    get_google_client,
    read_google_cookie,
    session_cookie,
    set_google_cookie,
    set_session_cookie,
    sign_in_with_google,
)
from app.core.config import get_settings
from app.core.db import get_db

router = APIRouter(prefix="/google")

# Editor page that shows a sign-in error. Never a URL from the request: no open redirect.
SIGN_IN_ERROR_PAGE = "/sign-in?error=google"
# Google's `code` and `state` are far shorter; the limits only stop oversized input.
CODE_MAX_LENGTH = 2048
STATE_MAX_LENGTH = 256


def google_client() -> GoogleClient:
    try:
        return get_google_client()
    except GoogleSignInUnavailable as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Google sign-in is not available."
        ) from error


@router.get(
    "",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    summary="Start Google sign-in",
    description="Redirects to Google. Open it in the browser, not with fetch.",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "Google not configured."}},
)
def start_google_sign_in(
    client: Annotated[GoogleClient, Depends(google_client)],
) -> RedirectResponse:
    authorization = client.start()
    response = RedirectResponse(authorization.url, status_code=status.HTTP_302_FOUND)
    set_google_cookie(response, authorization.state, authorization.code_verifier)
    return response


@router.get(
    "/callback",
    status_code=status.HTTP_302_FOUND,
    response_class=RedirectResponse,
    summary="Google sign-in callback",
    description=(
        "Google sends the user here. On success sets the session cookie and redirects to the "
        "editor; on any failure redirects to the editor's sign-in page with `?error=google`."
    ),
)
def finish_google_sign_in(
    db: Annotated[Session, Depends(get_db)],
    client: Annotated[GoogleClient, Depends(google_client)],
    previous_session: Annotated[str | None, Depends(session_cookie)],
    code: Annotated[str | None, Query(max_length=CODE_MAX_LENGTH)] = None,
    state: Annotated[str | None, Query(max_length=STATE_MAX_LENGTH)] = None,
    round_trip: Annotated[str | None, Cookie(alias=GOOGLE_COOKIE)] = None,
    user_agent: Annotated[str | None, Header()] = None,
) -> RedirectResponse:
    frontend_url = get_settings().frontend_url
    try:
        code_verifier = read_google_cookie(round_trip, state)
        if not code:
            raise GoogleSignInFailed
        profile = client.fetch_profile(code, code_verifier)
        signed_in = sign_in_with_google(db, profile, user_agent, previous_session)
    except GoogleSignInFailed:
        failure = RedirectResponse(
            f"{frontend_url}{SIGN_IN_ERROR_PAGE}", status_code=status.HTTP_302_FOUND
        )
        clear_google_cookie(failure)
        return failure
    response = RedirectResponse(frontend_url, status_code=status.HTTP_302_FOUND)
    clear_google_cookie(response)
    set_session_cookie(response, signed_in.session_token)
    return response
