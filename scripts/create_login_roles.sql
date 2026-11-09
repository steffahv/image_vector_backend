-- Creates one login user per service, each a member of its group role (created by migration 0004).
-- Run it after `alembic upgrade head`, as a user that can create roles (e.g. postgres).
-- Passwords are passed on the command line and never saved in the repo:
--
--   psql -d test_1 -v ON_ERROR_STOP=1 \
--     -v migrator_password=... -v platform_password=... -v agent_password=... \
--     -f scripts/create_login_roles.sql
--
-- Running it again changes the passwords and keeps the users.

SELECT format('CREATE ROLE %I LOGIN', name)
FROM (VALUES ('vectoredit_migrator_login'), ('vectoredit_platform_login'), ('vectoredit_agent_login'))
    AS users(name)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = name)
\gexec

ALTER ROLE vectoredit_migrator_login PASSWORD :'migrator_password';
ALTER ROLE vectoredit_platform_login PASSWORD :'platform_password';
ALTER ROLE vectoredit_agent_login PASSWORD :'agent_password';

GRANT vectoredit_migrator TO vectoredit_migrator_login;
GRANT vectoredit_platform TO vectoredit_platform_login;
GRANT vectoredit_agent TO vectoredit_agent_login;
