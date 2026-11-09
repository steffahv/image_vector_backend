"""The product account (`platform.accounts`) of a signed-in user, used by auth during sign-in.

Row-level security only shows an account to the session acting for it, or to the signed-in user it
belongs to. Sign-in knows the user before the account, so these functions mark the user as signed
in first (`set_current_user`); the caller then acts for the account with `set_current_account`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.core.db import set_current_user
from app.documents.models import Account, AgentMode

DEFAULT_LANGUAGE = "es"
NAME_MAX_LENGTH = 100


def find_account_id(db: Session, auth_user_id: uuid.UUID) -> uuid.UUID | None:
    set_current_user(db, auth_user_id)
    return db.scalar(select(Account.id).where(Account.auth_user_id == auth_user_id))


def get_or_create_account(db: Session, auth_user_id: uuid.UUID, name: str) -> uuid.UUID:
    """The user's account id, creating the account the first time they sign in.

    Two first sign-ins of the same user can run at once: ON CONFLICT lets the second one find the
    account the first one created instead of failing on the unique `auth_user_id`.
    """
    set_current_user(db, auth_user_id)
    db.execute(
        insert(Account)
        .values(
            auth_user_id=auth_user_id,
            name=name[:NAME_MAX_LENGTH],
            language=DEFAULT_LANGUAGE,
            agent_mode=AgentMode.PLATFORM,
        )
        .on_conflict_do_nothing(index_elements=[Account.auth_user_id])
    )
    account_id = find_account_id(db, auth_user_id)
    if account_id is None:
        raise RuntimeError("The account was neither created nor found")
    return account_id
