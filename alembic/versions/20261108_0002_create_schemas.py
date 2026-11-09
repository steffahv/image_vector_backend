"""Create the six PostgreSQL schemas. Tables are added by later migrations.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out instead of importing DbSchema: a migration must not change if the code changes later.
SCHEMAS = ("auth", "platform", "storage", "billing", "agent", "operations")


def upgrade() -> None:
    for schema in SCHEMAS:
        op.execute(f'CREATE SCHEMA IF NOT EXISTS "{schema}"')


def downgrade() -> None:
    # RESTRICT: fails if a schema still has tables, instead of silently dropping data.
    for schema in reversed(SCHEMAS):
        op.execute(f'DROP SCHEMA IF EXISTS "{schema}" RESTRICT')
