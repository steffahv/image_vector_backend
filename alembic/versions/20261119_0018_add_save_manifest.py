"""Keep what the editor declared for each file of a save until the save is committed (VEC-31).

The commit checks the uploaded bytes against the declared size, type, hash and dimensions, and
builds the revision's image map from it. Saves only exist from this task on, so the table is
empty and the column can be NOT NULL without a default.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-19
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "saves",
        sa.Column("manifest", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        schema="storage",
    )


def downgrade() -> None:
    op.drop_column("saves", "manifest", schema="storage")
