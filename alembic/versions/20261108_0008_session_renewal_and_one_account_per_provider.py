"""Renew sessions while they are used and allow one Google account per user.

- auth.sessions.last_used_at: lets VEC-4 extend a session on each use.
- auth.accounts UNIQUE (user_id, provider): one linked account per provider and person.
  It starts with user_id, so it replaces the separate user_id index.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-08 22:01:43.999441
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        op.f("uq_accounts_user_id_provider"), "accounts", ["user_id", "provider"], schema="auth"
    )
    # Dropped after the unique constraint exists, so user lookups always have an index.
    op.drop_index(op.f("ix_accounts_user_id"), table_name="accounts", schema="auth")
    op.add_column(
        "sessions",
        sa.Column(
            "last_used_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        schema="auth",
    )


def downgrade() -> None:
    op.drop_column("sessions", "last_used_at", schema="auth")
    op.drop_constraint(
        op.f("uq_accounts_user_id_provider"), "accounts", schema="auth", type_="unique"
    )
    op.create_index(
        op.f("ix_accounts_user_id"), "accounts", ["user_id"], unique=False, schema="auth"
    )
