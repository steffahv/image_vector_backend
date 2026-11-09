"""Sign-in: turn a proven identity (email link or Google) into a user, an account and a session.

The first sign-in creates the auth user and the product account. Each function runs in one
transaction: if any step fails, the link is not used up and nothing is half created.

`previous_session` is the session cookie the browser already had, if any. That session is ended:
signing in again must not leave the old token working, even if someone kept a copy of it.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import AuthUser, IdentityProvider, LinkedAccount
from app.auth.service.email_links import consume_sign_in_link
from app.auth.service.errors import GoogleSignInFailed
from app.auth.service.google import GoogleProfile
from app.auth.service.sessions import end_session, start_session
from app.auth.service.users import get_or_create_verified_user
from app.core.db import set_current_account
from app.documents.service import get_or_create_account


@dataclass(frozen=True)
class SignedIn:
    session_token: str
    user: AuthUser
    account_id: uuid.UUID


def sign_in_with_email_link(
    db: Session, token: str, user_agent: str | None, previous_session: str | None = None
) -> SignedIn:
    email = consume_sign_in_link(db, token)
    user = get_or_create_verified_user(db, email)
    return _start(db, user, user_agent, previous_session)


def sign_in_with_google(
    db: Session,
    profile: GoogleProfile,
    user_agent: str | None,
    previous_session: str | None = None,
) -> SignedIn:
    """Sign in with a Google identity, linking it to the user with the same email the first time.

    Linking by email is only safe when Google has verified that address: otherwise anyone could
    create a Google account with someone else's email and take over their account.
    """
    user = _linked_user(db, profile.subject)
    if user is None:
        if not profile.email_verified:
            raise GoogleSignInFailed
        user = get_or_create_verified_user(
            db, profile.email.lower(), name=profile.name, image_url=profile.picture
        )
        _link_google(db, user, profile.subject)
    return _start(db, user, user_agent, previous_session)


def _linked_user(db: Session, subject: str) -> AuthUser | None:
    return db.scalar(
        select(AuthUser)
        .join(LinkedAccount, LinkedAccount.user_id == AuthUser.id)
        .where(
            LinkedAccount.provider == IdentityProvider.GOOGLE,
            LinkedAccount.provider_account_id == subject,
        )
    )


def _link_google(db: Session, user: AuthUser, subject: str) -> None:
    # DO NOTHING on either unique key: the same Google account linked by a sign-in running at the
    # same time (fine), or this user already linked to another Google account (refused below).
    db.execute(
        insert(LinkedAccount)
        .values(user_id=user.id, provider=IdentityProvider.GOOGLE, provider_account_id=subject)
        .on_conflict_do_nothing()
    )
    linked = _linked_user(db, subject)
    if linked is None or linked.id != user.id:
        raise GoogleSignInFailed


def _start(
    db: Session, user: AuthUser, user_agent: str | None, previous_session: str | None
) -> SignedIn:
    if previous_session:
        end_session(db, previous_session)
    account_id = get_or_create_account(db, user.id, user.name or user.email.partition("@")[0])
    set_current_account(db, account_id)
    token = start_session(db, user.id, user_agent)
    db.commit()
    return SignedIn(session_token=token, user=user, account_id=account_id)
