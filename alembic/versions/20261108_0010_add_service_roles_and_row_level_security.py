"""Add the service roles, per-schema privileges and row-level security on platform.accounts.

Three NOLOGIN group roles. Each environment creates its own login users (with passwords that never
go in the repo) as members of them: see scripts/create_login_roles.sql and docs/base-de-datos.md.

- vectoredit_migrator: owns the schemas and every table. Alembic switches to it (alembic/env.py),
  so every new table has the same owner and the default privileges below apply to it.
- vectoredit_platform: the Python platform. Reads and writes its schemas.
- vectoredit_agent: the TypeScript agent. Reads auth and platform, writes only agent.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-08
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Written out instead of imported: a migration must not change if the code changes later.
MIGRATOR = "vectoredit_migrator"
PLATFORM = "vectoredit_platform"
AGENT = "vectoredit_agent"
ROLES = (MIGRATOR, PLATFORM, AGENT)

SCHEMAS = ("auth", "platform", "storage", "billing", "agent", "operations")

READ = "SELECT"
READ_WRITE = "SELECT, INSERT, UPDATE, DELETE"

# Schema -> role -> table privileges. A schema missing for a role means no access at all.
PRIVILEGES = {
    PLATFORM: {
        "auth": READ_WRITE,
        "platform": READ_WRITE,
        "storage": READ_WRITE,
        "billing": READ_WRITE,
        "operations": READ_WRITE,
        "agent": READ,
    },
    AGENT: {
        "auth": READ,
        "platform": READ,
        "agent": READ_WRITE,
    },
}

# Must match ACCOUNT_ID_SETTING in app/core/db.py.
ACCOUNT_ID_SETTING = "app.account_id"


def _create_roles() -> None:
    for role in ROLES:
        # Roles belong to the whole PostgreSQL server, so another database may have created them.
        op.execute(
            f"""
            DO $$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '{role}') THEN
                    CREATE ROLE {role} NOLOGIN;
                END IF;
            END
            $$
            """
        )
    # Whoever runs this migration must be able to SET ROLE to the migrator from now on.
    op.execute(f"GRANT {MIGRATOR} TO CURRENT_USER")


def _give_existing_objects_to_migrator() -> None:
    for schema in SCHEMAS:
        op.execute(f'ALTER SCHEMA "{schema}" OWNER TO {MIGRATOR}')
    schema_list = ", ".join(f"'{schema}'" for schema in SCHEMAS)
    op.execute(
        f"""
        DO $$
        DECLARE t record;
        BEGIN
            FOR t IN SELECT schemaname, tablename FROM pg_tables
                     WHERE schemaname IN ({schema_list})
            LOOP
                EXECUTE format('ALTER TABLE %I.%I OWNER TO {MIGRATOR}', t.schemaname, t.tablename);
            END LOOP;
            FOR t IN SELECT p.oid::regprocedure AS signature FROM pg_proc p
                     JOIN pg_namespace n ON n.oid = p.pronamespace
                     WHERE n.nspname IN ({schema_list})
            LOOP
                EXECUTE format('ALTER ROUTINE %s OWNER TO {MIGRATOR}', t.signature);
            END LOOP;
        END
        $$
        """
    )
    op.execute(f"ALTER TABLE public.alembic_version OWNER TO {MIGRATOR}")
    # Created by migration 0004 for PostgreSQL 17 and older; later migrations may replace it.
    op.execute(f"ALTER FUNCTION public.uuidv7() OWNER TO {MIGRATOR}")


def _grant_schema_privileges() -> None:
    for role, schemas in PRIVILEGES.items():
        for schema, privileges in schemas.items():
            op.execute(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}')
            op.execute(f'GRANT {privileges} ON ALL TABLES IN SCHEMA "{schema}" TO {role}')
            op.execute(f'GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA "{schema}" TO {role}')
            # Tables the migrator creates later get the same privileges with no extra step.
            op.execute(
                f'ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR} IN SCHEMA "{schema}" '
                f"GRANT {privileges} ON TABLES TO {role}"
            )
            op.execute(
                f'ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR} IN SCHEMA "{schema}" '
                f"GRANT USAGE, SELECT ON SEQUENCES TO {role}"
            )


def _enable_account_rls() -> None:
    # NULL when no account is set, so every policy matches nothing (fail closed).
    # current_setting(..., true) returns '' rather than NULL once a SET LOCAL has ended.
    op.execute(
        f"""
        CREATE FUNCTION platform.current_account_id() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT nullif(current_setting('{ACCOUNT_ID_SETTING}', true), '')::uuid $$
        """
    )
    op.execute("ALTER TABLE platform.accounts ENABLE ROW LEVEL SECURITY")
    # FORCE: the owner (the migrator) is filtered too. Only superusers skip RLS.
    op.execute("ALTER TABLE platform.accounts FORCE ROW LEVEL SECURITY")
    op.execute(
        """
        CREATE POLICY account_isolation ON platform.accounts
            USING (id = platform.current_account_id())
            WITH CHECK (id = platform.current_account_id())
        """
    )


def upgrade() -> None:
    _create_roles()
    _give_existing_objects_to_migrator()
    _grant_schema_privileges()
    _enable_account_rls()
    # The rest of this `alembic upgrade` run creates its objects as the migrator too.
    # Later runs switch in alembic/env.py.
    op.execute(f"SET ROLE {MIGRATOR}")


def downgrade() -> None:
    op.execute("DROP POLICY account_isolation ON platform.accounts")
    op.execute("ALTER TABLE platform.accounts NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.accounts DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION platform.current_account_id()")

    # Back to the user that connected, who takes the schemas and tables back.
    op.execute("RESET ROLE")
    op.execute(f"REASSIGN OWNED BY {MIGRATOR} TO SESSION_USER")
    # Revokes every privilege and default privilege of the roles in this database. One role at a
    # time: with all three at once PostgreSQL fails on the default privileges they share.
    for role in ROLES:
        op.execute(f"DROP OWNED BY {role}")
    for role in ROLES:
        # Still in use by another database on the same server: leave it for that one.
        op.execute(
            f"""
            DO $$
            BEGIN
                DROP ROLE IF EXISTS {role};
            EXCEPTION WHEN dependent_objects_still_exist THEN
                RAISE NOTICE 'Role {role} is still used by another database; not dropped';
            END
            $$
            """
        )
