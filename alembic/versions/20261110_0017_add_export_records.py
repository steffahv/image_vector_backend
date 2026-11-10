"""Add export records linked to jobs and stored files (VEC-41).

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-10 10:27:13.082974
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


OWN_EXPORT = (
    "account_id = platform.current_account_id()"
    " AND workspace_id IN (SELECT w.id FROM platform.workspaces w"
    " WHERE w.owner_id = platform.current_account_id())"
)


def upgrade() -> None:
    op.create_table(
        "exports",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("job_id", sa.Uuid(), nullable=False),
        sa.Column("object_id", sa.Uuid(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                "expired",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
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
            "status <> 'completed' OR object_id IS NOT NULL",
            name=op.f("ck_exports_completed_object"),
        ),
        sa.CheckConstraint(
            "status <> 'expired' OR object_id IS NULL", name=op.f("ck_exports_expired_object")
        ),
        sa.ForeignKeyConstraint(
            ["account_id"], ["platform.accounts.id"], name=op.f("fk_exports_account_id_accounts")
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "job_id"],
            ["operations.jobs.workspace_id", "operations.jobs.id"],
            name=op.f("fk_exports_workspace_id_job_id_jobs"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "object_id"],
            ["storage.objects.workspace_id", "storage.objects.id"],
            name=op.f("fk_exports_workspace_id_object_id_objects"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_exports_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_exports")),
        sa.UniqueConstraint("job_id", name=op.f("uq_exports_job_id")),
        schema="operations",
    )
    op.create_index(
        op.f("ix_exports_account_id"), "exports", ["account_id"], unique=False, schema="operations"
    )
    op.create_index(
        op.f("ix_exports_status_expires_at"),
        "exports",
        ["status", "expires_at"],
        unique=False,
        schema="operations",
    )
    op.create_index(
        op.f("ix_exports_workspace_id_object_id"),
        "exports",
        ["workspace_id", "object_id"],
        unique=False,
        schema="operations",
    )
    op.execute("ALTER TABLE operations.exports ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operations.exports FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY account_isolation ON operations.exports USING ({OWN_EXPORT})"
        f" WITH CHECK ({OWN_EXPORT}"
        " AND job_id IN (SELECT j.id FROM operations.jobs j WHERE j.type = 'generate_export')"
        " AND (object_id IS NULL OR object_id IN ("
        " SELECT o.id FROM storage.objects o WHERE o.kind = 'export')))"
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_exports_workspace_id_object_id"), table_name="exports", schema="operations"
    )
    op.drop_index(op.f("ix_exports_status_expires_at"), table_name="exports", schema="operations")
    op.drop_index(op.f("ix_exports_account_id"), table_name="exports", schema="operations")
    op.drop_table("exports", schema="operations")
