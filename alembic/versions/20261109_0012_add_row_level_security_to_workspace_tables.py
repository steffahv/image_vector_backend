"""Add row-level security to the workspaces and every platform and storage table of a workspace.

The model is platform.accounts (migration 0010):
- platform.workspaces: a session sees the workspaces its account owns.
- Every table with a workspace_id: a session sees the rows of those workspaces.

WITH CHECK repeats the same rule, so a row cannot be written into, or moved to, another account's
workspace. FORCE filters the owner (the migrator) too; only superusers skip it.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-09
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out instead of imported: a migration must not change if the code changes later.
OWNS_WORKSPACE = "owner_id = platform.current_account_id()"
IN_OWN_WORKSPACE = (
    "workspace_id IN (SELECT w.id FROM platform.workspaces w"
    " WHERE w.owner_id = platform.current_account_id())"
)

POLICIES = {
    "platform.workspaces": OWNS_WORKSPACE,
    "platform.folders": IN_OWN_WORKSPACE,
    "platform.documents": IN_OWN_WORKSPACE,
    "platform.document_revisions": IN_OWN_WORKSPACE,
    "platform.revision_images": IN_OWN_WORKSPACE,
    "platform.document_versions": IN_OWN_WORKSPACE,
    "platform.share_links": IN_OWN_WORKSPACE,
    "storage.objects": IN_OWN_WORKSPACE,
    "storage.uploads": IN_OWN_WORKSPACE,
    "storage.saves": IN_OWN_WORKSPACE,
    "storage.workspace_quotas": IN_OWN_WORKSPACE,
    "storage.byte_reservations": IN_OWN_WORKSPACE,
}


def upgrade() -> None:
    for table, rule in POLICIES.items():
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(f"CREATE POLICY account_isolation ON {table} USING ({rule}) WITH CHECK ({rule})")


def downgrade() -> None:
    for table in reversed(POLICIES):
        op.execute(f"DROP POLICY account_isolation ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
