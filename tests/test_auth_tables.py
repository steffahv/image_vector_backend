import hashlib
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.auth.models import (
    AuthSession,
    AuthUser,
    EmailVerification,
    IdentityProvider,
    LinkedAccount,
    PasswordCredential,
    VerificationPurpose,
)
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


def test_a_user_can_link_only_one_google_account(db: Session) -> None:
    user = _user(db)
    db.add(
        LinkedAccount(user_id=user.id, provider=IdentityProvider.GOOGLE, provider_account_id="g-1")
    )
    db.flush()

    db.add(
        LinkedAccount(user_id=user.id, provider=IdentityProvider.GOOGLE, provider_account_id="g-2")
    )
    with pytest.raises(IntegrityError, match="uq_accounts_user_id_provider"):
        db.flush()


def test_new_session_starts_as_just_used(db: Session) -> None:
    session = AuthSession(
        user_id=_user(db).id, token_hash=_token_hash("s1"), expires_at=_in_one_hour()
    )
    db.add(session)
    db.flush()
    db.refresh(session)

    assert session.last_used_at.tzinfo is not None


ARGON2ID_HASH = "$argon2id$v=19$m=65536,t=3,p=4$c2FsdHNhbHQ$aGFzaGhhc2hoYXNoaGFzaA"


def test_password_is_stored_only_as_argon2id_hash(db: Session) -> None:
    user = _user(db)
    db.add(PasswordCredential(user_id=user.id, password_hash="plain-text-password"))
    with pytest.raises(IntegrityError, match="ck_password_credentials_password_hash_argon2id"):
        db.flush()


def test_password_goes_with_its_user(db: Session) -> None:
    user = _user(db)
    db.add(PasswordCredential(user_id=user.id, password_hash=ARGON2ID_HASH))
    db.flush()

    db.execute(delete(AuthUser).where(AuthUser.id == user.id))
    assert db.get(PasswordCredential, user.id) is None


@pytest.mark.parametrize("purpose", list(VerificationPurpose))
def test_email_links_accept_every_purpose(db: Session, purpose: VerificationPurpose) -> None:
    db.add(
        EmailVerification(
            email="ana@example.com",
            purpose=purpose,
            token_hash=_token_hash(f"link-{purpose}"),
            expires_at=_in_one_hour(),
        )
    )
    db.flush()
