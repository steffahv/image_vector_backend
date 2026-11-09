"""Add the service roles, per-schema privileges and row-level security on platform.accounts.

Three NOLOGIN group roles. Each environment creates its own login users (with passwords that never
go in the repo) as members of them: see scripts/create_login_roles.sql and docs/base-de-datos.md.

- vectoredit_migrator: owns the schemas and every table. Alembic switches to it (alembic/env.py),
  so every new table has the same owner and the default privileges below apply to it.
- vectoredit_platform: the Python platform. Reads and writes its schemas.
- vectoredit_agent: the TypeScript agent. Reads platform and, in auth, only users and sessions
  (never password hashes or email links). Writes only agent.

Row-level security on platform.accounts: a session sees the account it acts for, or the account
of the signed-in user. The second case is how sign-in finds or creates the account before its id
is known. A trigger keeps an account's id and auth user fixed, so no account can take the place
of another.

Functions the migrator creates later are not executable by anyone until a migration grants them:
the credit functions (VEC-41) will skip RLS on purpose, so only the roles named may call them.

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
        "platform": READ,
        "agent": READ_WRITE,
    },
}

# In auth the agent gets single tables, not the schema: it only validates sessions. Granting the
# whole schema would also expose password hashes, email link hashes and any future auth table.
AGENT_AUTH_TABLES = ("users", "sessions")

# Must match ACCOUNT_ID_SETTING and USER_ID_SETTING in app/core/db.py.
ACCOUNT_ID_SETTING = "app.account_id"
USER_ID_SETTING = "app.user_id"


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
    op.execute(f"GRANT USAGE ON SCHEMA auth TO {AGENT}")
    for table in AGENT_AUTH_TABLES:
        op.execute(f"GRANT SELECT ON auth.{table} TO {AGENT}")
    # PostgreSQL lets everyone (PUBLIC) execute a new function. Not for the migrator's: each one
    # gets GRANT EXECUTE to the roles that need it, in the migration that creates it.
    op.execute(
        f"ALTER DEFAULT PRIVILEGES FOR ROLE {MIGRATOR} REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC"
    )


def _setting_function(name: str, setting: str) -> None:
    # NULL when nothing is set, so every policy matches nothing (fail closed).
    # current_setting(..., true) returns '' rather than NULL once a SET LOCAL has ended.
    op.execute(
        f"""
        CREATE FUNCTION platform.{name}() RETURNS uuid
        LANGUAGE sql STABLE
        AS $$ SELECT nullif(current_setting('{setting}', true), '')::uuid $$
        """
    )
    # Created before this migration switches to the migrator, so hand it over like the rest.
    op.execute(f"ALTER FUNCTION platform.{name}() OWNER TO {MIGRATOR}")


def _enable_account_rls() -> None:
    _setting_function("current_account_id", ACCOUNT_ID_SETTING)
    _setting_function("current_auth_user_id", USER_ID_SETTING)
    op.execute("ALTER TABLE platform.accounts ENABLE ROW LEVEL SECURITY")
    # FORCE: the owner (the migrator) is filtered too. Only superusers skip RLS.
    op.execute("ALTER TABLE platform.accounts FORCE ROW LEVEL SECURITY")
    # The account it acts for, or the signed-in user's own account: sign-in knows the user
    # before the account, and must find it (or create it the first time).
    op.execute(
        """
        CREATE POLICY account_isolation ON platform.accounts
            USING (
                id = platform.current_account_id()
                OR auth_user_id = platform.current_auth_user_id()
            )
            WITH CHECK (
                id = platform.current_account_id()
                OR auth_user_id = platform.current_auth_user_id()
            )
        """
    )
    # The policy lets an account update its own row; without this it could also change its id or
    # point auth_user_id to another user, and take over that user's sign-in.
    op.execute(
        """
        CREATE FUNCTION platform.accounts_keep_identity() RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            IF NEW.id <> OLD.id OR NEW.auth_user_id <> OLD.auth_user_id THEN
                RAISE EXCEPTION 'an account cannot change its id or auth user'
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END
        $$
        """
    )
    op.execute(f"ALTER FUNCTION platform.accounts_keep_identity() OWNER TO {MIGRATOR}")
    op.execute(
        """
        CREATE TRIGGER accounts_keep_identity
            BEFORE UPDATE OF id, auth_user_id ON platform.accounts
            FOR EACH ROW EXECUTE FUNCTION platform.accounts_keep_identity()
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
    op.execute("DROP TRIGGER IF EXISTS accounts_keep_identity ON platform.accounts")
    op.execute("DROP FUNCTION IF EXISTS platform.accounts_keep_identity()")
    op.execute("DROP POLICY account_isolation ON platform.accounts")
    op.execute("ALTER TABLE platform.accounts NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE platform.accounts DISABLE ROW LEVEL SECURITY")
    op.execute("DROP FUNCTION platform.current_account_id()")
    op.execute("DROP FUNCTION IF EXISTS platform.current_auth_user_id()")

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
