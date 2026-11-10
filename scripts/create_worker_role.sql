-- Run as a role administrator after upgrading the database.
-- psql -d test_1 -v ON_ERROR_STOP=1 -v worker_password=... -f scripts/create_worker_role.sql

SELECT format('CREATE ROLE %I %s', name, login)
FROM (VALUES ('vectoredit_worker', 'NOLOGIN'), ('vectoredit_worker_login', 'LOGIN'))
    AS roles(name, login)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = name)
\gexec

ALTER ROLE vectoredit_worker_login PASSWORD :'worker_password';
GRANT vectoredit_platform TO vectoredit_worker;
GRANT vectoredit_worker TO vectoredit_worker_login;
GRANT DELETE ON operations.jobs TO vectoredit_worker;
