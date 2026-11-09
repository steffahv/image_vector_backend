"""Add passwords, email verification links and password reset links.

- auth.password_credentials: optional password per user, stored as an Argon2id hash,
  with a failed-attempts counter to stop password guessing.
- auth.verifications.purpose: besides sign_in, now verify_email and password_reset.
  Alembic does not detect CHECK changes, so that part is written by hand.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-08 22:08:17.302190
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "password_credentials",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("password_hash", sa.Text(), nullable=False),
        sa.Column("failed_attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "starts_with(password_hash, '$argon2id$')",
            name=op.f("ck_password_credentials_password_hash_argon2id"),
        ),
        sa.CheckConstraint(
            "failed_attempts >= 0",
            name=op.f("ck_password_credentials_failed_attempts_non_negative"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_password_credentials_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", name=op.f("pk_password_credentials")),
        schema="auth",
    )
    _set_purposes(PURPOSES_AFTER)


def downgrade() -> None:
    # Links for the new purposes would break the old CHECK.
    op.execute("DELETE FROM auth.verifications WHERE purpose <> 'sign_in'")
    _set_purposes(PURPOSES_BEFORE)
    op.drop_table("password_credentials", schema="auth")


PURPOSES_BEFORE = ["sign_in"]
PURPOSES_AFTER = ["sign_in", "verify_email", "password_reset"]


def _set_purposes(purposes: list[str]) -> None:
    allowed = ", ".join(f"'{purpose}'" for purpose in purposes)
    op.drop_constraint(
        op.f("ck_verifications_purpose"), "verifications", schema="auth", type_="check"
    )
    op.create_check_constraint(
        op.f("ck_verifications_purpose"), "verifications", f"purpose IN ({allowed})", schema="auth"
    )
