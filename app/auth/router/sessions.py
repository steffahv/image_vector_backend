from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.auth.schemas import CurrentUserResponse, SessionCreate
from app.auth.service import (
    CurrentUser,
    InvalidEmailLink,
    clear_session_cookie,
    get_current_user,
    session_cookie,
    set_session_cookie,
    sign_in_with_email_link,
    sign_out,
    sign_out_everywhere,
)
from app.core.db import get_db

router = APIRouter()

NOT_SIGNED_IN_RESPONSE: dict[int | str, dict[str, Any]] = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Not signed in."}
}


@router.post(
    "/sessions",
    status_code=status.HTTP_201_CREATED,
    response_model=CurrentUserResponse,
    summary="Sign in with the token of an email link",
    description=(
        "Uses up the link and sets the session cookie. A link works only once. "
        "If the browser already had a session, that one is ended."
    ),
    responses={status.HTTP_400_BAD_REQUEST: {"description": "Invalid, used or expired link."}},
)
def create_session(
    body: SessionCreate,
    response: Response,
    db: Annotated[Session, Depends(get_db)],
    previous_session: Annotated[str | None, Depends(session_cookie)],
    user_agent: Annotated[str | None, Header()] = None,
) -> CurrentUserResponse:
    try:
        signed_in = sign_in_with_email_link(db, body.token, user_agent, previous_session)
    except InvalidEmailLink as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="This sign-in link is invalid or has expired."
        ) from error
    set_session_cookie(response, signed_in.session_token)
    user = signed_in.user
    return CurrentUserResponse(
        user_id=user.id,
        account_id=signed_in.account_id,
        email=user.email,
        name=user.name,
        image_url=user.image_url,
    )


@router.get(
    "/sessions/current",
    response_model=CurrentUserResponse,
    summary="Get the signed-in user",
    responses=NOT_SIGNED_IN_RESPONSE,
)
def read_current_session(
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> CurrentUserResponse:
    return CurrentUserResponse(
        user_id=current.user_id,
        account_id=current.account_id,
        email=current.email,
        name=current.name,
        image_url=current.image_url,
    )


@router.delete(
    "/sessions/current",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Sign out",
    description="Ends the session in the database and clears the cookie. Safe to repeat.",
)
def delete_current_session(
    db: Annotated[Session, Depends(get_db)],
    token: Annotated[str | None, Depends(session_cookie)],
) -> Response:
    if token:
        sign_out(db, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response


@router.delete(
    "/sessions",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Sign out on every device",
    description="Ends every session of the signed-in user, this one included.",
    responses=NOT_SIGNED_IN_RESPONSE,
)
def delete_all_sessions(
    db: Annotated[Session, Depends(get_db)],
    current: Annotated[CurrentUser, Depends(get_current_user)],
) -> Response:
    sign_out_everywhere(db, current.user_id)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    clear_session_cookie(response)
    return response
