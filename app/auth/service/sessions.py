"""Sessions: start one after sign-in, find the user behind a cookie, rotate it and end it.

The cookie holds a random token; `auth.sessions` only its SHA-256 hash, so a leaked database does
not hand out live sessions.

Renewal with rotation: when a session is used over an hour after its last renewal, its end is
pushed forward and its token replaced. The browser gets the new token in the response; all its
tabs share the cookie, so they switch at once. The previous token is still accepted for a grace
period (2 minutes, set in `auth.find_session()`), for requests already on their way. Used after
that, the cookie was copied (only one of the copies got the new token), so the session is ended
for both: the person signs in again, whoever holds the copy is out.

Whether a token is valid is decided by the SQL function `auth.find_session()` (migration 0011),
which the agent calls too.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import timedelta

from sqlalchemy import delete, func, insert, or_, text, update
from sqlalchemy.orm import Session

from app.auth.models import AuthSession, AuthUser
from app.auth.service.tokens import hash_token, new_token

logger = logging.getLogger(__name__)

# Sliding sessions: each use pushes the end forward, so an active user stays signed in.
SESSION_TTL = timedelta(days=30)
# Renew (and rotate) at most once per hour, so not every request writes to the database.
SESSION_RENEW_AFTER = timedelta(hours=1)
USER_AGENT_MAX_LENGTH = 512

_FIND_SESSION = text(
    "SELECT session_id, user_id, is_previous_token FROM auth.find_session(:token_hash)"
)


@dataclass(frozen=True)
class FoundSession:
    user: AuthUser
    # Set when this request rotated the token: the cookie must be replaced with it.
    new_token: str | None


def start_session(db: Session, user_id: uuid.UUID, user_agent: str | None) -> str:
    """Create a session and return its token, for the cookie. Not committed."""
    token = new_token()
    db.execute(
        insert(AuthSession).values(
            user_id=user_id,
            token_hash=hash_token(token),
            expires_at=func.now() + SESSION_TTL,
            user_agent=user_agent[:USER_AGENT_MAX_LENGTH] if user_agent else None,
        )
    )
    return token


def find_session(db: Session, token: str) -> FoundSession | None:
    """The user of a live session, rotating its token when it is due. Commits when it changes."""
    token_hash = hash_token(token)
    row = db.execute(_FIND_SESSION, {"token_hash": token_hash}).first()
    if row is None:
        _end_if_reused(db, token_hash)
        return None
    user = db.get_one(AuthUser, row.user_id)
    # A previous token within the grace period is accepted as is: the browser already has the
    # new one, from the response of the request that rotated it.
    if row.is_previous_token:
        return FoundSession(user=user, new_token=None)
    return FoundSession(user=user, new_token=_rotate_if_due(db, row.session_id, token_hash))


def _rotate_if_due(db: Session, session_id: uuid.UUID, token_hash: bytes) -> str | None:
    token = new_token()
    # Conditional on the current hash: of two requests at once, only one rotates. The other one
    # read the session before, and its token is still accepted as the previous one.
    rotated = db.scalar(
        update(AuthSession)
        .where(
            AuthSession.id == session_id,
            AuthSession.token_hash == token_hash,
            AuthSession.last_used_at < func.now() - SESSION_RENEW_AFTER,
        )
        .values(
            token_hash=hash_token(token),
            previous_token_hash=token_hash,
            rotated_at=func.now(),
            last_used_at=func.now(),
            expires_at=func.now() + SESSION_TTL,
        )
        .returning(AuthSession.id)
    )
    if rotated is None:
        return None
    db.commit()
    return token


def _end_if_reused(db: Session, token_hash: bytes) -> None:
    """A replaced token used after the grace period: the cookie was copied. End the session."""
    ended = db.scalar(
        delete(AuthSession)
        .where(AuthSession.previous_token_hash == token_hash)
        .returning(AuthSession.id)
    )
    if ended is not None:
        db.commit()
        # The session id only: never the token or the user's email.
        logger.warning("Session %s ended: a replaced token was used again", ended)


def end_session(db: Session, token: str) -> None:
    """Delete the session, so its cookie stops working even if someone kept a copy. Not committed.

    Matches the previous token too: the browser may still hold it right after a rotation.
    """
    token_hash = hash_token(token)
    db.execute(
        delete(AuthSession).where(
            or_(AuthSession.token_hash == token_hash, AuthSession.previous_token_hash == token_hash)
        )
    )


def sign_out(db: Session, token: str) -> None:
    end_session(db, token)
    db.commit()


def sign_out_everywhere(db: Session, user_id: uuid.UUID) -> None:
    """End every session of the user, e.g. after losing a device."""
    db.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    db.commit()
