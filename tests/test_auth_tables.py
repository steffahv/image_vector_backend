import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import AuthSession, AuthUser, EmailVerification, VerificationPurpose
from app.documents.models import Account, AgentMode


def _token_hash(token: str) -> bytes:
    return hashlib.sha256(token.encode()).digest()


def _user(db: Session, email: str = "ana@example.com") -> AuthUser:
    user = AuthUser(email=email)
    db.add(user)
    db.flush()
    return user


def _in_one_hour() -> datetime:
    return datetime.now(UTC) + timedelta(hours=1)


def test_user_gets_id_and_timestamps_from_the_database(db: Session) -> None:
    user = _user(db)
    db.refresh(user)

    assert user.id is not None
    assert user.created_at.tzinfo is not None


def test_email_must_be_lowercase(db: Session) -> None:
    db.add(AuthUser(email="Ana@Example.com"))
    with pytest.raises(IntegrityError, match="ck_users_email_lowercase"):
        db.flush()


def test_email_is_unique(db: Session) -> None:
    _user(db)
    db.add(AuthUser(email="ana@example.com"))
    with pytest.raises(IntegrityError, match="uq_users_email"):
        db.flush()


def test_session_token_hash_must_be_sha256(db: Session) -> None:
    user = _user(db)
    db.add(AuthSession(user_id=user.id, token_hash=b"short", expires_at=_in_one_hour()))
    with pytest.raises(IntegrityError, match="ck_sessions_token_hash_sha256"):
        db.flush()


def test_verification_does_not_need_a_registered_user(db: Session) -> None:
    db.add(
        EmailVerification(
            email="new@example.com",
            purpose=VerificationPurpose.SIGN_IN,
            token_hash=_token_hash("link-token"),
            expires_at=_in_one_hour(),
        )
    )
    db.flush()


def test_agent_mode_only_accepts_known_values(db: Session) -> None:
    user = _user(db)
    db.add(Account(auth_user_id=user.id, name="Ana", language="es", agent_mode="free_for_all"))
    with pytest.raises(IntegrityError, match="ck_accounts_agent_mode"):
        db.flush()


def test_deleting_a_user_removes_sessions_but_not_their_product_account(db: Session) -> None:
    user = _user(db)
    db.add(AuthSession(user_id=user.id, token_hash=_token_hash("s1"), expires_at=_in_one_hour()))
    db.flush()

    # Sessions depend only on the user, so they go with it.
    db.execute(delete(AuthUser).where(AuthUser.id == user.id))
    assert db.scalars(select(AuthSession).where(AuthSession.user_id == user.id)).all() == []

    # The product account must block deleting its identity (no silent cascade).
    other = _user(db, "luis@example.com")
    db.add(
        Account(auth_user_id=other.id, name="Luis", language="es", agent_mode=AgentMode.PLATFORM)
    )
    db.flush()
    with pytest.raises(IntegrityError, match="fk_accounts_auth_user_id_users"):
        db.execute(delete(AuthUser).where(AuthUser.id == other.id))
