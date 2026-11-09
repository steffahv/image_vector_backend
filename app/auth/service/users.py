"""Finding or creating the auth user behind a sign-in, once its email has been proven."""

from datetime import UTC, datetime

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.auth.models import AuthUser, PasswordCredential


def get_or_create_verified_user(
    db: Session, email: str, name: str | None = None, image_url: str | None = None
) -> AuthUser:
    """The user with this email, created the first time. Only call it once the email is proven.

    Two first sign-ins with the same email can run at once: ON CONFLICT lets the second one find
    the user the first one created instead of failing on the unique email.
    """
    db.execute(
        insert(AuthUser)
        .values(email=email, name=name, image_url=image_url)
        .on_conflict_do_nothing(index_elements=[AuthUser.email])
    )
    user = db.scalars(select(AuthUser).where(AuthUser.email == email)).one()
    if user.email_verified_at is None:
        _verify_email(db, user)
    return user


def _verify_email(db: Session, user: AuthUser) -> None:
    """Mark the email as proven, and drop any password set before it was.

    Whoever set that password never proved they own the address: it may be someone who signed up
    with another person's email, waiting for the owner to verify it and share the account.
    """
    db.execute(delete(PasswordCredential).where(PasswordCredential.user_id == user.id))
    user.email_verified_at = datetime.now(UTC)
    db.flush()
