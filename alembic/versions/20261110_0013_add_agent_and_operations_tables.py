"""Add the agent tables and the operations tables that need no job (VEC-41).

agent: conversations, messages, runs, pending_calls, period_quotas, reservations, rates, usage.
operations: audit_log, object_copies, backup_runs. `exports` waits for `jobs` (VEC-36).

Row-level security, as in migration 0012, on every table with account data:
- conversations and runs: the session's account, in one of its workspaces.
- messages (by conversation), pending_calls and usage (by run): those of the session's account.
- period_quotas and reservations: the session's account.
- object_copies: copies of the files of the account's workspaces.
- audit_log: it reads only the entries of its own workspaces. A session with no account may add
  an entry anywhere; one with an account only in its own workspaces.
rates and backup_runs are global and hold no account data, so they have no policy.

Privileges narrower than the schema defaults of migration 0010:
- The agent changes quotas and reservations only through the quota functions (VEC-30), never
  directly; it reads rates but cannot change prices; it writes usage once and never edits it.
- The platform assigns period quotas and adds rates (it otherwise only reads agent).
- Nobody updates or deletes audit entries.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out instead of imported: a migration must not change if the code changes later.
PLATFORM = "vectoredit_platform"
AGENT = "vectoredit_agent"

OWN_ACCOUNT = "account_id = platform.current_account_id()"
OWN_WORKSPACES = (
    "SELECT w.id FROM platform.workspaces w WHERE w.owner_id = platform.current_account_id()"
)
IN_OWN_WORKSPACE = f"workspace_id IN ({OWN_WORKSPACES})"
OF_OWN_CONVERSATION = (
    "conversation_id IN (SELECT c.id FROM agent.conversations c"
    " WHERE c.account_id = platform.current_account_id())"
)
OF_OWN_RUN = (
    "run_id IN (SELECT r.id FROM agent.runs r WHERE r.account_id = platform.current_account_id())"
)
# Audit entries: a session with no account (a failed sign-in, an anonymous share link) may add
# one to any workspace, but a session with an account only to its own workspaces, so it cannot
# plant an entry in another account's log.
AUDIT_APPEND = (
    f"workspace_id IS NULL OR platform.current_account_id() IS NULL OR {IN_OWN_WORKSPACE}"
)
OF_OWN_OBJECT = (
    f"object_id IN (SELECT o.id FROM storage.objects o WHERE o.workspace_id IN ({OWN_WORKSPACES}))"
)

# Same rule for reading and writing (USING and WITH CHECK).
POLICIES = {
    "agent.conversations": f"{OWN_ACCOUNT} AND {IN_OWN_WORKSPACE}",
    "agent.runs": f"{OWN_ACCOUNT} AND {IN_OWN_WORKSPACE}",
    "agent.messages": OF_OWN_CONVERSATION,
    "agent.pending_calls": OF_OWN_RUN,
    "agent.usage": OF_OWN_RUN,
    "agent.period_quotas": OWN_ACCOUNT,
    "agent.reservations": OWN_ACCOUNT,
    "operations.object_copies": OF_OWN_OBJECT,
}

GRANTS = (
    f"REVOKE INSERT, UPDATE, DELETE ON agent.period_quotas, agent.reservations FROM {AGENT}",
    f"REVOKE INSERT, UPDATE, DELETE ON agent.rates FROM {AGENT}",
    f"REVOKE UPDATE, DELETE ON agent.usage FROM {AGENT}",
    f"GRANT INSERT, UPDATE ON agent.period_quotas TO {PLATFORM}",
    f"GRANT INSERT ON agent.rates TO {PLATFORM}",
    f"REVOKE UPDATE, DELETE ON operations.audit_log FROM {PLATFORM}",
)


def _enable_row_level_security() -> None:
    for table, rule in POLICIES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY account_isolation ON {table} USING ({rule}) WITH CHECK ({rule})")
    # Audit entries are written in contexts with no account (a failed sign-in, an anonymous
    # share link), so any session may add one (see AUDIT_APPEND); reading stays limited to its
    # own workspaces.
    op.execute("ALTER TABLE operations.audit_log ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE operations.audit_log FORCE ROW LEVEL SECURITY")
    op.execute(
        f"CREATE POLICY audit_append ON operations.audit_log FOR INSERT WITH CHECK ({AUDIT_APPEND})"
    )
    op.execute(
        f"CREATE POLICY account_isolation ON operations.audit_log FOR SELECT"
        f" USING ({IN_OWN_WORKSPACE})"
    )


def upgrade() -> None:
    _create_tables()
    _enable_row_level_security()
    for statement in GRANTS:
        op.execute(statement)


def _create_tables() -> None:
    op.create_table(
        "rates",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_price_micro", sa.BigInteger(), nullable=False),
        sa.Column("output_price_micro", sa.BigInteger(), nullable=False),
        sa.Column("currency", sa.Text(), nullable=False),
        sa.Column("token_basis", sa.BigInteger(), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "input_price_micro >= 0", name=op.f("ck_rates_input_price_micro_non_negative")
        ),
        sa.CheckConstraint(
            "output_price_micro >= 0", name=op.f("ck_rates_output_price_micro_non_negative")
        ),
        sa.CheckConstraint("token_basis > 0", name=op.f("ck_rates_token_basis_positive")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_rates")),
        schema="agent",
    )
    op.create_index(
        op.f("ix_rates_provider_model_effective_from"),
        "rates",
        ["provider", "model", "effective_from"],
        unique=False,
        schema="agent",
    )
    op.create_table(
        "backup_runs",
        sa.Column(
            "type",
            sa.Enum(
                "database",
                "objects",
                name="type",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "succeeded",
                "failed",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("manifest", sa.Text(), nullable=True),
        sa.Column("recovery_point_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verification_result", sa.Text(), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.CheckConstraint(
            "finished_at >= started_at", name=op.f("ck_backup_runs_finishes_after_start")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_backup_runs")),
        schema="operations",
    )
    op.create_table(
        "period_quotas",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("allocated", sa.BigInteger(), nullable=False),
        sa.Column("reserved", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column("consumed", sa.BigInteger(), server_default="0", nullable=False),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("allocated >= 0", name=op.f("ck_period_quotas_allocated_non_negative")),
        sa.CheckConstraint("consumed >= 0", name=op.f("ck_period_quotas_consumed_non_negative")),
        sa.CheckConstraint("ends_at > starts_at", name=op.f("ck_period_quotas_ends_after_start")),
        sa.CheckConstraint(
            "reserved + consumed <= allocated", name=op.f("ck_period_quotas_within_allocated")
        ),
        sa.CheckConstraint("reserved >= 0", name=op.f("ck_period_quotas_reserved_non_negative")),
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform.accounts.id"],
            name=op.f("fk_period_quotas_account_id_accounts"),
        ),
        sa.PrimaryKeyConstraint(
            "account_id", "period_id", "resource", name=op.f("pk_period_quotas")
        ),
        schema="agent",
    )
    op.create_table(
        "audit_log",
        sa.Column("actor_ref", sa.Text(), nullable=True),
        sa.Column("workspace_id", sa.Uuid(), nullable=True),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("entity_type", sa.Text(), nullable=False),
        sa.Column("entity_id", sa.Text(), nullable=True),
        sa.Column(
            "result",
            sa.Enum(
                "success",
                "denied",
                "error",
                name="result",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_audit_log_workspace_id_workspaces"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_log")),
        schema="operations",
    )
    op.create_index(
        op.f("ix_audit_log_created_at"),
        "audit_log",
        ["created_at"],
        unique=False,
        schema="operations",
    )
    op.create_index(
        op.f("ix_audit_log_workspace_id"),
        "audit_log",
        ["workspace_id"],
        unique=False,
        schema="operations",
    )
    op.create_table(
        "object_copies",
        sa.Column("object_id", sa.Uuid(), nullable=False),
        sa.Column("destination", sa.Text(), nullable=False),
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("sha256", sa.LargeBinary(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "octet_length(sha256) = 32", name=op.f("ck_object_copies_sha256_length")
        ),
        sa.CheckConstraint(
            "size_bytes >= 0", name=op.f("ck_object_copies_size_bytes_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["object_id"], ["storage.objects.id"], name=op.f("fk_object_copies_object_id_objects")
        ),
        sa.PrimaryKeyConstraint("object_id", "destination", name=op.f("pk_object_copies")),
        schema="operations",
    )
    op.create_table(
        "conversations",
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["account_id"],
            ["platform.accounts.id"],
            name=op.f("fk_conversations_account_id_accounts"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["platform.documents.workspace_id", "platform.documents.id"],
            name=op.f("fk_conversations_workspace_id_document_id_documents"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id"],
            ["platform.workspaces.id"],
            name=op.f("fk_conversations_workspace_id_workspaces"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conversations")),
        sa.UniqueConstraint(
            "account_id",
            "workspace_id",
            "id",
            name=op.f("uq_conversations_account_id_workspace_id_id"),
        ),
        schema="agent",
    )
    op.create_index(
        op.f("ix_conversations_workspace_id_document_id"),
        "conversations",
        ["workspace_id", "document_id"],
        unique=False,
        schema="agent",
    )
    op.create_table(
        "messages",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("sequence", sa.BigInteger(), nullable=False),
        sa.Column(
            "role",
            sa.Enum(
                "user",
                "assistant",
                "tool",
                name="role",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("content", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("sequence > 0", name=op.f("ck_messages_sequence_positive")),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["agent.conversations.id"],
            name=op.f("fk_messages_conversation_id_conversations"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_messages")),
        sa.UniqueConstraint(
            "conversation_id", "sequence", name=op.f("uq_messages_conversation_id_sequence")
        ),
        schema="agent",
    )
    op.create_table(
        "runs",
        sa.Column("conversation_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("workspace_id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("editor_session_id", sa.Uuid(), nullable=False),
        sa.Column("initial_revision", sa.BigInteger(), nullable=False),
        sa.Column("pre_agent_version_id", sa.Uuid(), nullable=True),
        sa.Column("recorded_pre_agent_version_id", sa.Uuid(), nullable=True),
        sa.Column(
            "mode",
            sa.Enum(
                "platform",
                "own_key",
                name="mode",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("variant", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("catalog_fingerprint", sa.Text(), nullable=False),
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
            nullable=False,
        ),
        sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "initial_revision >= 0", name=op.f("ck_runs_initial_revision_non_negative")
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "workspace_id", "conversation_id"],
            [
                "agent.conversations.account_id",
                "agent.conversations.workspace_id",
                "agent.conversations.id",
            ],
            name=op.f("fk_runs_account_id_workspace_id_conversation_id_conversations"),
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id", "pre_agent_version_id"],
            [
                "platform.document_versions.workspace_id",
                "platform.document_versions.document_id",
                "platform.document_versions.id",
            ],
            name=op.f("fk_runs_workspace_id_document_id_pre_agent_version_id_document_versions"),
            ondelete="SET NULL (pre_agent_version_id)",
        ),
        sa.ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["platform.documents.workspace_id", "platform.documents.id"],
            name=op.f("fk_runs_workspace_id_document_id_documents"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_runs")),
        sa.UniqueConstraint("account_id", "id", name=op.f("uq_runs_account_id_id")),
        schema="agent",
    )
    op.create_index(
        op.f("ix_runs_account_id_workspace_id_conversation_id"),
        "runs",
        ["account_id", "workspace_id", "conversation_id"],
        unique=False,
        schema="agent",
    )
    op.create_index(
        op.f("ix_runs_status_lease_until"),
        "runs",
        ["status", "lease_until"],
        unique=False,
        schema="agent",
    )
    op.create_index(
        op.f("ix_runs_workspace_id_document_id_pre_agent_version_id"),
        "runs",
        ["workspace_id", "document_id", "pre_agent_version_id"],
        unique=False,
        schema="agent",
    )
    op.create_index(
        "uq_runs_document_id_editor_session_id_active",
        "runs",
        ["document_id", "editor_session_id"],
        unique=True,
        schema="agent",
        postgresql_where="status IN ('pending', 'running')",
    )
    op.create_table(
        "pending_calls",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("call_id", sa.Text(), nullable=False),
        sa.Column("tool", sa.Text(), nullable=False),
        sa.Column("arguments_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "pending",
                "completed",
                "failed",
                "expired",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["agent.runs.id"],
            name=op.f("fk_pending_calls_run_id_runs"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pending_calls")),
        sa.UniqueConstraint("run_id", "call_id", name=op.f("uq_pending_calls_run_id_call_id")),
        schema="agent",
    )
    op.create_index(
        op.f("ix_pending_calls_status_expires_at"),
        "pending_calls",
        ["status", "expires_at"],
        unique=False,
        schema="agent",
    )
    op.create_table(
        "reservations",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("account_id", sa.Uuid(), nullable=False),
        sa.Column("period_id", sa.Uuid(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("amount", sa.BigInteger(), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "reserved",
                "settled",
                "released",
                name="status",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
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
        sa.CheckConstraint("amount > 0", name=op.f("ck_reservations_amount_positive")),
        sa.ForeignKeyConstraint(
            ["account_id", "period_id", "resource"],
            [
                "agent.period_quotas.account_id",
                "agent.period_quotas.period_id",
                "agent.period_quotas.resource",
            ],
            name=op.f("fk_reservations_account_id_period_id_resource_period_quotas"),
        ),
        sa.ForeignKeyConstraint(
            ["account_id", "run_id"],
            ["agent.runs.account_id", "agent.runs.id"],
            name=op.f("fk_reservations_account_id_run_id_runs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_reservations")),
        sa.UniqueConstraint("run_id", "resource", name=op.f("uq_reservations_run_id_resource")),
        schema="agent",
    )
    op.create_index(
        op.f("ix_reservations_account_id_period_id_resource"),
        "reservations",
        ["account_id", "period_id", "resource"],
        unique=False,
        schema="agent",
    )
    op.create_index(
        op.f("ix_reservations_account_id_run_id"),
        "reservations",
        ["account_id", "run_id"],
        unique=False,
        schema="agent",
    )
    op.create_index(
        op.f("ix_reservations_status_expires_at"),
        "reservations",
        ["status", "expires_at"],
        unique=False,
        schema="agent",
    )
    op.create_table(
        "usage",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("rate_id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("resource", sa.Text(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.BigInteger(), nullable=False),
        sa.Column("output_tokens", sa.BigInteger(), nullable=False),
        sa.Column("units", sa.BigInteger(), nullable=False),
        sa.Column("estimated_cost_micro", sa.BigInteger(), nullable=False),
        sa.Column("charged", sa.Boolean(), nullable=False),
        sa.Column(
            "result",
            sa.Enum(
                "success",
                "error",
                "cancelled",
                name="result",
                native_enum=False,
                create_constraint=True,
                length=None,
            ),
            nullable=False,
        ),
        sa.Column("duration_ms", sa.BigInteger(), nullable=False),
        sa.Column("id", sa.Uuid(), server_default=sa.text("uuidv7()"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint("duration_ms >= 0", name=op.f("ck_usage_duration_ms_non_negative")),
        sa.CheckConstraint(
            "estimated_cost_micro >= 0", name=op.f("ck_usage_estimated_cost_micro_non_negative")
        ),
        sa.CheckConstraint("input_tokens >= 0", name=op.f("ck_usage_input_tokens_non_negative")),
        sa.CheckConstraint("output_tokens >= 0", name=op.f("ck_usage_output_tokens_non_negative")),
        sa.CheckConstraint("units >= 0", name=op.f("ck_usage_units_non_negative")),
        sa.ForeignKeyConstraint(
            ["rate_id"], ["agent.rates.id"], name=op.f("fk_usage_rate_id_rates")
        ),
        sa.ForeignKeyConstraint(["run_id"], ["agent.runs.id"], name=op.f("fk_usage_run_id_runs")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_usage")),
        sa.UniqueConstraint(
            "run_id", "event_id", "resource", name=op.f("uq_usage_run_id_event_id_resource")
        ),
        schema="agent",
    )
    op.create_index(op.f("ix_usage_rate_id"), "usage", ["rate_id"], unique=False, schema="agent")


def downgrade() -> None:
    # Policies and privileges go with their tables.
    op.drop_index(op.f("ix_usage_rate_id"), table_name="usage", schema="agent")
    op.drop_table("usage", schema="agent")
    op.drop_index(
        op.f("ix_reservations_status_expires_at"), table_name="reservations", schema="agent"
    )
    op.drop_index(
        op.f("ix_reservations_account_id_run_id"), table_name="reservations", schema="agent"
    )
    op.drop_index(
        op.f("ix_reservations_account_id_period_id_resource"),
        table_name="reservations",
        schema="agent",
    )
    op.drop_table("reservations", schema="agent")
    op.drop_index(
        op.f("ix_pending_calls_status_expires_at"), table_name="pending_calls", schema="agent"
    )
    op.drop_table("pending_calls", schema="agent")
    op.drop_index(
        "uq_runs_document_id_editor_session_id_active",
        table_name="runs",
        schema="agent",
        postgresql_where="status IN ('pending', 'running')",
    )
    op.drop_index(
        op.f("ix_runs_workspace_id_document_id_pre_agent_version_id"),
        table_name="runs",
        schema="agent",
    )
    op.drop_index(op.f("ix_runs_status_lease_until"), table_name="runs", schema="agent")
    op.drop_index(
        op.f("ix_runs_account_id_workspace_id_conversation_id"), table_name="runs", schema="agent"
    )
    op.drop_table("runs", schema="agent")
    op.drop_table("messages", schema="agent")
    op.drop_index(
        op.f("ix_conversations_workspace_id_document_id"),
        table_name="conversations",
        schema="agent",
    )
    op.drop_table("conversations", schema="agent")
    op.drop_table("object_copies", schema="operations")
    op.drop_index(op.f("ix_audit_log_workspace_id"), table_name="audit_log", schema="operations")
    op.drop_index(op.f("ix_audit_log_created_at"), table_name="audit_log", schema="operations")
    op.drop_table("audit_log", schema="operations")
    op.drop_table("period_quotas", schema="agent")
    op.drop_table("backup_runs", schema="operations")
    op.drop_index(
        op.f("ix_rates_provider_model_effective_from"), table_name="rates", schema="agent"
    )
    op.drop_table("rates", schema="agent")
