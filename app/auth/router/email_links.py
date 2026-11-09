from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.schemas import (
    EmailLinkCreate,
    EmailLinkPreviewResponse,
    EmailLinkResponse,
    EmailLinkToken,
)
from app.auth.service import (
    EmailDeliveryUnavailable,
    EmailSender,
    InvalidEmailLink,
    TooManyEmailLinks,
    get_email_sender,
    preview_sign_in_link,
    request_sign_in_link,
)
from app.core.db import get_db

router = APIRouter()

# Same answer whether or not the email has an account, so it never tells which exist.
LINK_SENT = "If the address can receive email, a sign-in link is on its way."


def email_sender() -> EmailSender:
    try:
        return get_email_sender()
    except EmailDeliveryUnavailable as error:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="Email sign-in is not available yet."
        ) from error


@router.post(
    "/email-links",
    status_code=status.HTTP_202_ACCEPTED,
    response_model=EmailLinkResponse,
    summary="Send a one-time sign-in link by email",
    description=(
        "Works for new and existing emails alike: the first sign-in creates the account. "
        "The link opens the editor, which sends its token to `POST /auth/sessions`."
    ),
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Too many links for this email."},
        status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "No email provider configured."},
    },
)
def create_email_link(
    body: EmailLinkCreate,
    db: Annotated[Session, Depends(get_db)],
    sender: Annotated[EmailSender, Depends(email_sender)],
) -> EmailLinkResponse:
    try:
        request_sign_in_link(db, body.email, sender)
    except TooManyEmailLinks as error:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many sign-in links requested. Try again in a few minutes.",
        ) from error
    return EmailLinkResponse(detail=LINK_SENT)


@router.post(
    "/email-links/preview",
    response_model=EmailLinkPreviewResponse,
    summary="See which email a sign-in link is for, without using it",
    description=(
        "The editor shows it and asks for confirmation before `POST /auth/sessions`, so a link "
        "sent by someone else cannot sign the user in to that person's account unnoticed. "
        "POST so the token never travels in a URL."
    ),
    responses={status.HTTP_400_BAD_REQUEST: {"description": "Invalid, used or expired link."}},
)
def preview_email_link(
    body: EmailLinkToken, db: Annotated[Session, Depends(get_db)]
) -> EmailLinkPreviewResponse:
    try:
        email = preview_sign_in_link(db, body.token)
    except InvalidEmailLink as error:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, detail="This sign-in link is invalid or has expired."
        ) from error
    return EmailLinkPreviewResponse(email=email)
