"""Add indexes for account deletion and sign-in link cleanup.

- platform.workspaces.owner_id: finding an account's workspaces no longer scans the table.
- auth.verifications.expires_at: the cleanup job finds expired links directly.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-08 21:53:59.054033
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        op.f("ix_verifications_expires_at"),
        "verifications",
        ["expires_at"],
        unique=False,
        schema="auth",
    )
    op.create_index(
        op.f("ix_workspaces_owner_id"), "workspaces", ["owner_id"], unique=False, schema="platform"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_workspaces_owner_id"), table_name="workspaces", schema="platform")
    op.drop_index(op.f("ix_verifications_expires_at"), table_name="verifications", schema="auth")
