"""`get_current_user`: the dependency that tells every route who is calling.

Any route that needs a session declares it; without a live session it answers 401. It also sets
the account on the database session (`set_current_account`), so row-level security filters every
later query of the request by that account.
"""

import uuid
from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyCookie
from sqlalchemy.orm import Session

from app.auth.service.cookies import SESSION_COOKIE, send_rotated_token
from app.auth.service.sessions import find_session
from app.core.db import get_db, set_current_account
from app.documents.service import find_account_id

# Also declares the cookie in OpenAPI, so Swagger marks the routes that need a session.
session_cookie = APIKeyCookie(
    name=SESSION_COOKIE, auto_error=False, description="Session cookie set by sign-in."
)


def _not_signed_in() -> HTTPException:
    return HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Not signed in.")


@dataclass(frozen=True)
class CurrentUser:
    user_id: uuid.UUID
    account_id: uuid.UUID
    email: str
    name: str | None
    image_url: str | None


def get_current_user(
    request: Request,
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Depends(session_cookie)],
) -> CurrentUser:
    if not token:
        raise _not_signed_in()
    found = find_session(db, token)
    if found is None:
        raise _not_signed_in()
    account_id = find_account_id(db, found.user.id)
    if account_id is None:
        raise _not_signed_in()
    set_current_account(db, account_id)
    if found.new_token is not None:
        # The token was rotated: from now on the browser must send the new one. Sent by
        # SessionCookieMiddleware, so it also reaches the browser if the route then fails.
        send_rotated_token(request, found.new_token)
    return CurrentUser(
        user_id=found.user.id,
        account_id=account_id,
        email=found.user.email,
        name=found.user.name,
        image_url=found.user.image_url,
    )
