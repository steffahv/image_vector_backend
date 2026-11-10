"""Add the persistent jobs queue (VEC-36).

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-10 09:55:33.512378
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RETIRED_SCHEDULED_JOB = (
    "status IN ('completed', 'failed', 'cancelled')"
    " AND split_part(idempotency_key, ':', 2) = 'scheduled'"
    " AND type <> 'generate_export'"
)
WORKER = "pg_has_role(current_user, to_regrole('vectoredit_worker'), 'USAGE')"
IN_OWN_WORKSPACE = (
    "workspace_id IN (SELECT w.id FROM platform.workspaces w"
    " WHERE w.owner_id = platform.current_account_id())"
)


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("type", sa.Text(), nullable=False),
        sa.Column("idempotency_key", sa.Text(), nullable=False),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "running",
                "completed",
                "failed",
                "cancelled",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            server_default="pending",
            nullable=False,
        ),
        sa.Column("attempts", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column(
            "next_run_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_code", sa.Text(), nullable=True),
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
            "(status = 'running') = (lease_until IS NOT NULL)", name=op.f("ck_jobs_running_lease")
        ),
        sa.CheckConstraint("jsonb_typeof(payload) = 'object'", name=op.f("ck_jobs_payload_object")),
        sa.CheckConstraint("attempts >= 0", name=op.f("ck_jobs_attempts_non_negative")),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_jobs_workspace_id_workspaces"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_jobs")),
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_jobs_idempotency_key")),
        sa.UniqueConstraint("workspace_id", "id", name=op.f("uq_jobs_workspace_id_id")),
        schema="operations",
    )
    op.create_index(
        op.f("ix_jobs_status_lease_until"),
        "jobs",
        ["status", "lease_until"],
        unique=False,
        schema="operations",
    )
    op.create_index(
        op.f("ix_jobs_status_next_run_at"),
        "jobs",
        ["status", "next_run_at"],
        unique=False,
        schema="operations",
    )
    op.create_index(
        "ix_jobs_retention",
        "jobs",
        ["updated_at", "id"],
        schema="operations",
        postgresql_where=sa.text(RETIRED_SCHEDULED_JOB),
    )
    op.execute("ALTER TABLE operations.jobs ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operations.jobs FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY job_owner_read ON operations.jobs FOR SELECT USING ({IN_OWN_WORKSPACE})"
    )
    op.execute(
        "CREATE POLICY job_owner_enqueue ON operations.jobs FOR INSERT"
        f" WITH CHECK ({IN_OWN_WORKSPACE}"
        " AND split_part(idempotency_key, ':', 1) = workspace_id::text"
        " AND split_part(idempotency_key, ':', 2) <> 'scheduled'"
        " AND type NOT IN ('expire_uploads_and_reservations', 'purge_trash', 'prune_versions',"
        " 'delete_unused_objects', 'reconcile_storage_quotas', 'expire_exports')"
        " AND status = 'pending' AND attempts = 0 AND error_code IS NULL)"
    )
    # The role is provisioned by the database administrator, not by the migrator.
    op.execute(
        f"CREATE POLICY job_worker ON operations.jobs USING ({WORKER}) WITH CHECK ({WORKER})"
    )
    op.execute(
        "CREATE POLICY job_worker_purge ON operations.jobs AS RESTRICTIVE FOR DELETE"
        f" USING ({WORKER} AND {RETIRED_SCHEDULED_JOB}"
        " AND updated_at < statement_timestamp() - interval '30 days')"
    )
    op.execute("REVOKE DELETE ON operations.jobs FROM vectoredit_platform")
    op.execute(
        """
        DO $$
        BEGIN
            IF to_regrole('vectoredit_worker') IS NOT NULL THEN
                GRANT DELETE ON operations.jobs TO vectoredit_worker;
            END IF;
        END
        $$;
        """
    )
    op.execute(
        "CREATE POLICY job_worker_list_workspaces ON platform.workspaces FOR SELECT"
        f" USING ({WORKER} AND platform.current_account_id() IS NULL)"
    )


def downgrade() -> None:
    op.execute("DROP POLICY job_worker_list_workspaces ON platform.workspaces")
    op.drop_index(op.f("ix_jobs_status_next_run_at"), table_name="jobs", schema="operations")
    op.drop_index(op.f("ix_jobs_status_lease_until"), table_name="jobs", schema="operations")
    op.drop_table("jobs", schema="operations")
