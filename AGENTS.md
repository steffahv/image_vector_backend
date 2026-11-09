# AGENTS.md

Guide for anyone writing or reviewing code in this repo, person or AI assistant. It is short on purpose: the
details are in `docs/` (in Spanish). This file holds the rules that cannot be skipped and what to check
before handing in a change.

## What this repo is

The VectorEdit platform backend: FastAPI, SQLAlchemy 2, Alembic and PostgreSQL 17. A modular monolith
(`app/<module>/` with `router/`, `schemas/`, `service/` and `models/`). It shares the database with the
agent, a separate TypeScript service.

| To learn about... | Read |
|---|---|
| Modules, layers and how they talk | [docs/arquitectura.md](docs/arquitectura.md) |
| Naming, style, adding routes or modules | [docs/convenciones.md](docs/convenciones.md) |
| Tables, migrations, roles and row-level security | [docs/base-de-datos.md](docs/base-de-datos.md) |
| Setup, running, tests and CI | [docs/desarrollo.md](docs/desarrollo.md) |
| How to write tests that catch real risks | [.claude/skills/risk-scenario-tests/SKILL.md](.claude/skills/risk-scenario-tests/SKILL.md) |

Code, database names and comments in English; documentation in `docs/` in Spanish.

## Security: rules that are never skipped

### Data and access

- **Every table with account data gets its RLS policy** in the same migration that creates it, with its
  test in `tests/test_database_security.py`. Without a policy, any role that can read the table sees every
  account's rows.
- **The account is set with `set_current_account()`** (and, only during sign-in, `set_current_user()`).
  Never filter "by hand" trusting an `account_id` sent in the request.
- **An id sent by the client is not proof of permission.** Before reading or changing a document, folder or
  file, the service checks that it belongs to the account's workspace. RLS is the second barrier, not the
  only one.
- **Least privilege.** The agent reads only what it needs; never grant a whole schema when one table is
  enough. Every new function gets an explicit `GRANT EXECUTE`; a `SECURITY DEFINER` function also gets
  `SET search_path = pg_catalog, pg_temp`, fully qualified names, and checks the account itself.
- **The app never runs as a superuser or as the migrator** outside development (`check_app_role()`).

### Secrets and sensitive data

- No credentials, tokens or passwords in code, tests or docs. Everything is read with `get_settings()`;
  new variables go to `.env.example` without real values.
- For any token (session, email link, share link) **only its SHA-256 hash is stored**; when compared in
  Python, use constant time (`hmac.compare_digest`).
- Passwords only with Argon2id. Never log passwords, hashes, tokens or full email addresses.
- Error responses do not reveal whether an email exists, nor internal details (SQL, paths, stack traces).

### Input

- All input goes through a Pydantic schema with limits: max text length, number ranges, capped lists and a
  max file size.
- SQL only through SQLAlchemy or bound parameters. Never `f"... {value}"` inside a query. In migrations,
  interpolated names are constants of the file itself, never data.
- Files: check the type by content, not by extension; upload with short-lived signed URLs. S3 keys are
  never built from user text.

### Sessions and requests

- Session cookies are `HttpOnly`, `Secure` and `SameSite`. Actions that change data use `POST`/`PUT`/
  `PATCH`/`DELETE`, never `GET`.
- Sign-in, password recovery and email links are rate limited.
- Every endpoint states who may call it. By default, a new route requires a session.

## Clean code and reuse

- **Search before writing.** Check `app/core/` (mixins, helpers such as `sha256_check`, `text_enum`), other
  modules' `service/` and `tests/factories.py`. If it exists, use it; if it almost exists, extend it.
- **Extract the second time you write something**, not before. No "just in case" abstractions.
- Short single-purpose functions, names that say what they do, types everywhere (strict mypy).
- A module uses another **through its `service`**, never by reading its tables. Routers do not touch the
  database.
- Comments explain why. No dead code, no commented-out code, no `TODO` without a Jira task.
- Explicit errors: no `except: pass`, no `except Exception` that hides failures.
- Every change comes with its tests, written as in the
  [risk-scenario tests skill](.claude/skills/risk-scenario-tests/SKILL.md). Database rules (CHECK, UQ, FK,
  RLS) are tested against PostgreSQL.

## Before handing in: required review

Before opening a PR (or calling a change done), review the diff against this list:

1. **Security gaps.** A new table without RLS? A role with more rights than it needs? Input without
   validation or limits? A secret, token or personal data in code, logs or responses? A client id used
   without checking who owns it?
2. **Logic bugs.** Edge cases (empty, duplicate, concurrency, retries), transactions that can be left half
   done, a `downgrade` that does not restore the database.
3. **Reuse.** Was something duplicated that already existed in `core/`, another service or the factories?
4. **Clean code.** Names, function and file size, useful comments, no debugging leftovers.
5. **Tests and CI.** The risk scenarios are covered, not only the happy path.

   ```bash
   ruff check . && ruff format --check .
   mypy
   pytest
   ```

   With a migration: `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head` and
   `alembic check`.
6. **Docs.** If a rule, a table or a setup step changed, update `docs/`.

If you find a problem outside what you are changing, report it in the PR or in Jira; do not fix it on the
side without saying so.

## Branches, commits and PRs

- One branch per Jira task: `feature/VEC-<n>-<description>`.
- Commits in English, starting with the task number (`VEC-30: ...`) and a body that explains why.
- A PR passes CI and gets a review before it is merged into `main`. No direct pushes to `main`.
- No process notes in the repo (who decided what, when): those go in Jira or in the PR.
