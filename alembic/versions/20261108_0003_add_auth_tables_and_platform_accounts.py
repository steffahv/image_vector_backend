"""Add the auth tables (users, accounts, sessions, verifications) and platform.accounts (VEC-29).

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-08 19:34:51.070181
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_users_email_lowercase")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
        schema="auth",
    )
    op.create_table(
        "verifications",
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column(
            "purpose",
            sa.Enum(
                "sign_in", name="purpose", native_enum=False, create_constraint=True, length=None
            ),
            nullable=False,
        ),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.CheckConstraint("email = lower(email)", name=op.f("ck_verifications_email_lowercase")),
        sa.CheckConstraint(
            "octet_length(token_hash) = 32", name=op.f("ck_verifications_token_hash_sha256")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_verifications")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_verifications_token_hash")),
        schema="auth",
    )
    op.create_index(
        op.f("ix_verifications_email"), "verifications", ["email"], unique=False, schema="auth"
    )
    op.create_table(
        "accounts",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column(
            "provider",
            sa.Enum(
                "google", name="provider", native_enum=False, create_constraint=True, length=None
            ),
            nullable=False,
        ),
        sa.Column("provider_account_id", sa.Text(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_accounts_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint(
            "provider", "provider_account_id", name=op.f("uq_accounts_provider_provider_account_id")
        ),
        schema="auth",
    )
    op.create_index(
        op.f("ix_accounts_user_id"), "accounts", ["user_id"], unique=False, schema="auth"
    )
    op.create_table(
        "sessions",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.LargeBinary(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
            "octet_length(token_hash) = 32", name=op.f("ck_sessions_token_hash_sha256")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["auth.users.id"],
            name=op.f("fk_sessions_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sessions")),
        sa.UniqueConstraint("token_hash", name=op.f("uq_sessions_token_hash")),
        schema="auth",
    )
    op.create_index(
        op.f("ix_sessions_expires_at"), "sessions", ["expires_at"], unique=False, schema="auth"
    )
    op.create_index(
        op.f("ix_sessions_user_id"), "sessions", ["user_id"], unique=False, schema="auth"
    )
    op.create_table(
        "accounts",
        sa.Column("auth_user_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("language", sa.Text(), nullable=False),
        sa.Column(
            "agent_mode",
            sa.Enum(
                "platform",
                "own_key",
                name="agent_mode",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("last_access_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deletion_requested_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
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
        sa.ForeignKeyConstraint(
            ["auth_user_id"], ["auth.users.id"], name=op.f("fk_accounts_auth_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_accounts")),
        sa.UniqueConstraint("auth_user_id", name=op.f("uq_accounts_auth_user_id")),
        schema="platform",
    )


def downgrade() -> None:
    op.drop_table("accounts", schema="platform")
    op.drop_index(op.f("ix_sessions_user_id"), table_name="sessions", schema="auth")
    op.drop_index(op.f("ix_sessions_expires_at"), table_name="sessions", schema="auth")
    op.drop_table("sessions", schema="auth")
    op.drop_index(op.f("ix_accounts_user_id"), table_name="accounts", schema="auth")
    op.drop_table("accounts", schema="auth")
    op.drop_index(op.f("ix_verifications_email"), table_name="verifications", schema="auth")
    op.drop_table("verifications", schema="auth")
    op.drop_table("users", schema="auth")
