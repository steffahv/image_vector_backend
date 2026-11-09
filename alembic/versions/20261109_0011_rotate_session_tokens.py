"""Rotate session tokens and look sessions up with one shared function (VEC-4).

- auth.sessions.previous_token_hash and rotated_at: each renewal replaces the token. The previous
  one is accepted for a short grace period, for requests already on their way; used after that,
  the cookie was copied and the platform ends the session.
- auth.find_session(token_hash): the single place that decides whether a token is valid. The
  platform and the agent both call it, so the rule is not written twice in two languages.
  SECURITY INVOKER (the default): it reads auth.sessions with the caller's own rights, which both
  roles already have. Read-only: only the platform ends sessions.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out instead of imported: a migration must not change if the code changes later.
PLATFORM = "vectoredit_platform"
AGENT = "vectoredit_agent"
# How long a replaced token is still accepted. Tested in tests/test_auth_sign_in.py.
ROTATION_GRACE = "2 minutes"


def upgrade() -> None:
    op.add_column(
        "sessions", sa.Column("previous_token_hash", sa.LargeBinary(), nullable=True), schema="auth"
    )
    op.add_column(
        "sessions",
        sa.Column("rotated_at", sa.DateTime(timezone=True), nullable=True),
        schema="auth",
    )
    op.create_check_constraint(
        op.f("ck_sessions_previous_token_hash_sha256"),
        "sessions",
        "octet_length(previous_token_hash) = 32",
        schema="auth",
    )
    op.create_index(
        op.f("ix_sessions_previous_token_hash"),
        "sessions",
        ["previous_token_hash"],
        unique=False,
        schema="auth",
    )
    # Fixed search_path and qualified names, so no object in another schema can stand in for
    # auth.sessions or now().
    op.execute(
        f"""
        CREATE FUNCTION auth.find_session(token_hash bytea)
        RETURNS TABLE (session_id uuid, user_id uuid, is_previous_token boolean)
        LANGUAGE sql STABLE
        SET search_path = pg_catalog, pg_temp
        AS $$
            SELECT s.id, s.user_id, false
            FROM auth.sessions s
            WHERE s.token_hash = find_session.token_hash
              AND s.expires_at > pg_catalog.now()
            UNION ALL
            SELECT s.id, s.user_id, true
            FROM auth.sessions s
            WHERE s.previous_token_hash = find_session.token_hash
              AND s.rotated_at > pg_catalog.now() - interval '{ROTATION_GRACE}'
              AND s.expires_at > pg_catalog.now()
        $$
        """
    )
    op.execute(f"GRANT EXECUTE ON FUNCTION auth.find_session(bytea) TO {PLATFORM}, {AGENT}")


def downgrade() -> None:
    op.execute("DROP FUNCTION auth.find_session(bytea)")
    op.drop_index(op.f("ix_sessions_previous_token_hash"), table_name="sessions", schema="auth")
    op.drop_constraint(
        op.f("ck_sessions_previous_token_hash_sha256"), "sessions", schema="auth", type_="check"
    )
    op.drop_column("sessions", "rotated_at", schema="auth")
    op.drop_column("sessions", "previous_token_hash", schema="auth")
