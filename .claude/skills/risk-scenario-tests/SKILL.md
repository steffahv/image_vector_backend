---
name: risk-scenario-tests
description: Use when writing or reviewing tests in this backend, especially for database rules, row-level security, roles and privileges, sessions, sign-in, or anything that keeps one account's data away from another. Tests the real risk scenarios, not just that each rule exists.
---

# Risk-scenario tests

A test is worth writing when it would catch a real failure: one account seeing another's data, an identity
leaking between requests, a role with more rights than it needs, or a future change silently undoing a
protection. Model: `tests/test_database_security.py`.

## Principles

1. **Test the scenario, not only the rule.** "The database rejects X" proves a constraint exists. Also
   write the case a user or attacker would hit: two accounts, one tries to read, change, delete or take over
   the other's rows.
2. **Never test security as a superuser.** Superusers skip RLS, so a test run as one passes for the wrong
   reason. Switch roles inside the test transaction with `SET LOCAL ROLE` (helper `as_role` in `tests/conftest.py`), and say why
   in the module docstring.
3. **Repeat the scenario for every role it applies to.** Use `pytest.mark.parametrize` over
   `PLATFORM_ROLE`, `AGENT_ROLE` and `MIGRATOR_ROLE`: a policy that works for one role and not another is a
   leak.
4. **Assert the effect, not just "no error".** Rows visible (`== {ana.id}`), `rowcount == 0` on a blocked
   update or delete, the exact error (`match="row-level security"`, `match="permission denied"`, or the
   constraint name).
5. **Reproduce the hard-to-see failures.** If the risk only shows up under reuse or concurrency, force it:
   a pool of one connection to prove the identity does not leak to the next request (compare
   `pg_backend_pid()`), a rolled-back savepoint, two sign-ins of the same new user.
6. **Guard the future.** When a protection must also hold for things created later, create a probe
   (a table or function made as the migrator) and assert it gets exactly the expected privileges. A later
   change that breaks the default stops the build.
7. **Test with the real login users in CI** when the rule depends on how a service connects (see
   `AGENT_DATABASE_URL`). Skip with a clear reason when the variable is not set locally.
8. **Be precise about why it failed.** Match the constraint or policy name, so a test that fails for another
   reason does not pass.
9. **Leave nothing behind.** Use the `db` fixture (rolled back after each test). A test that needs real
   commits uses its own session and writes no rows, or cleans up.

## Recipes

Two accounts and a restricted role:

```python
@pytest.mark.parametrize("role", [PLATFORM_ROLE, AGENT_ROLE, MIGRATOR_ROLE])
def test_each_account_sees_only_itself(db, two_accounts, role):
    ana, luis = two_accounts  # created as the test user, before switching role
    as_role(db, role)
    set_current_account(db, ana.id)
    assert _visible_account_ids(db) == {ana.id}
```

Blocked write, asserting the effect:

```python
updated = db.execute(update(Account).where(Account.id == luis.id).values(name="hacked"))
assert updated.rowcount == 0
```

Future objects get the right privileges:

```python
as_role(db, MIGRATOR_ROLE)
db.execute(text("CREATE TABLE platform.privileges_probe (id int)"))
db.execute(text("RESET ROLE"))
assert not _has_privilege(db, AGENT_ROLE, "platform.privileges_probe", "INSERT")
```

## Checklist for a new table with account data

- [ ] Account A cannot read, update or delete account B's rows, for each role that has access.
- [ ] Account A cannot insert a row for account B (`WITH CHECK`).
- [ ] A row cannot be moved to another account or workspace by an update.
- [ ] With no account set, no rows are visible.
- [ ] Roles without access get `permission denied`, not just an empty result.
- [ ] Any helper function used by the policy is executable by the roles that query the table.

## Reuse

`as_role` lives in `tests/conftest.py`; `two_accounts`, `_visible_account_ids` and `_has_privilege` live in
`tests/test_database_security.py`. When a second test file needs them, move them to `tests/conftest.py` or
`tests/factories.py` instead of copying them. Build rows with `tests/factories.py`.
