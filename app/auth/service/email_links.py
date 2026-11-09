"""One-time sign-in links sent by email.

The link opens the editor, which sends the token back with POST: consuming it changes data, so it
is never a GET, and mail scanners that open links do not use it up. The token goes in the URL
fragment (`#token=`), which the browser never sends to a server or in a Referer header.
"""

from datetime import timedelta

from sqlalchemy import ColumnElement, func, insert, select, update
from sqlalchemy.orm import Session

from app.auth.models import EmailVerification, VerificationPurpose
from app.auth.service.email_delivery import EmailSender
from app.auth.service.errors import InvalidEmailLink, TooManyEmailLinks
from app.auth.service.tokens import hash_token, new_token
from app.core.config import get_settings

EMAIL_LINK_TTL = timedelta(minutes=15)
# At most this many links per email in the window. Stops flooding someone's inbox, and with a
# 32-byte token there is nothing to guess, so consuming links needs no limit of its own.
EMAIL_LINK_LIMIT = 3
EMAIL_LINK_WINDOW = timedelta(minutes=15)
# Page of the editor that reads the token and sends it to POST /auth/sessions.
EMAIL_LINK_PAGE = "/sign-in/email"


def request_sign_in_link(db: Session, email: str, sender: EmailSender) -> None:
    """Send a sign-in link, whether or not the email has an account yet.

    Same behaviour for known and unknown emails, so the response never tells which exist.
    """
    # One request per email at a time, so two at once cannot both pass the limit.
    db.execute(select(func.pg_advisory_xact_lock(func.hashtext(email))))
    recent = db.scalar(
        select(func.count())
        .select_from(EmailVerification)
        .where(
            EmailVerification.email == email,
            EmailVerification.purpose == VerificationPurpose.SIGN_IN,
            EmailVerification.created_at > func.now() - EMAIL_LINK_WINDOW,
        )
    )
    if recent is not None and recent >= EMAIL_LINK_LIMIT:
        raise TooManyEmailLinks

    token = new_token()
    db.execute(
        insert(EmailVerification).values(
            email=email,
            purpose=VerificationPurpose.SIGN_IN,
            token_hash=hash_token(token),
            expires_at=func.now() + EMAIL_LINK_TTL,
        )
    )
    # Committed before sending, so the link already works when it arrives.
    db.commit()
    sender.send_sign_in_link(email, f"{get_settings().frontend_url}{EMAIL_LINK_PAGE}#token={token}")


def _usable_sign_in_link(token: str) -> tuple[ColumnElement[bool], ...]:
    return (
        EmailVerification.token_hash == hash_token(token),
        EmailVerification.purpose == VerificationPurpose.SIGN_IN,
        EmailVerification.used_at.is_(None),
        EmailVerification.expires_at > func.now(),
    )


def preview_sign_in_link(db: Session, token: str) -> str:
    """The email a sign-in link is for, without using it up.

    Lets the editor ask "Sign in as ana@example.com?" before signing in, so a link someone else
    sent (for their own account) cannot sign the user in to that account unnoticed. It reveals
    nothing new: whoever holds the token can already sign in with it.
    """
    email = db.scalar(select(EmailVerification.email).where(*_usable_sign_in_link(token)))
    if email is None:
        raise InvalidEmailLink
    return email


def consume_sign_in_link(db: Session, token: str) -> str:
    """Use up a sign-in link and return its email. Not committed.

    A single conditional UPDATE: of two requests with the same link, the second waits for the
    first and then finds it used, so a link can never start two sessions.
    """
    email = db.scalar(
        update(EmailVerification)
        .where(*_usable_sign_in_link(token))
        .values(used_at=func.now())
        .returning(EmailVerification.email)
    )
    if email is None:
        raise InvalidEmailLink
    return email
