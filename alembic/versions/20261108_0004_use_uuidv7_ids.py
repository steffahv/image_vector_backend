"""Generate ids with UUIDv7 (time-ordered) instead of random UUIDv4.

Random ids land anywhere in a primary key index, so large tables fragment it.
UUIDv7 starts with the creation time in milliseconds, so new rows go to the end of the index.

PostgreSQL 18 ships `uuidv7()` natively; up to 17 it does not exist, so this migration
creates `public.uuidv7()`. Unqualified calls look in `pg_catalog` first, so on PostgreSQL 18
the native function is used and this one is simply ignored.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-08 22:10:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables created before this migration whose `id` default changes.
TABLES_WITH_UUID_ID = [
    ("auth", "users"),
    ("auth", "accounts"),
    ("auth", "sessions"),
    ("auth", "verifications"),
    ("platform", "accounts"),
]

# Takes a random UUIDv4, writes the Unix time in milliseconds over its first 48 bits
# and turns the version bits from 4 (0100) into 7 (0111). The variant bits stay valid.
CREATE_UUIDV7 = """
CREATE OR REPLACE FUNCTION public.uuidv7() RETURNS uuid
LANGUAGE sql VOLATILE PARALLEL SAFE
AS $$
    SELECT encode(
        set_bit(
            set_bit(
                overlay(
                    uuid_send(gen_random_uuid())
                    PLACING substring(
                        int8send(floor(extract(epoch FROM clock_timestamp()) * 1000)::bigint)
                        FROM 3
                    )
                    FROM 1 FOR 6
                ),
                52, 1
            ),
            53, 1
        ),
        'hex'
    )::uuid
$$
"""


def upgrade() -> None:
    op.execute(CREATE_UUIDV7)
    for schema, table in TABLES_WITH_UUID_ID:
        op.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN id SET DEFAULT uuidv7()")


def downgrade() -> None:
    for schema, table in TABLES_WITH_UUID_ID:
        op.execute(f"ALTER TABLE {schema}.{table} ALTER COLUMN id SET DEFAULT gen_random_uuid()")
    op.execute("DROP FUNCTION public.uuidv7()")
