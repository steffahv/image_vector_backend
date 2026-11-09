@AGENTS.md

## For Claude Code

- Answer the user in Spanish; code, comments and commits in English.
- When writing or reviewing tests, use the `risk-scenario-tests` skill (`.claude/skills/`).
- Before calling a change done, run the "Before handing in" review from AGENTS.md on your diff and say what
  you found, even if it is "nothing".
- Run ruff, mypy and pytest before handing in (the suite is fast); with a migration, also upgrade,
  downgrade and `alembic check`.
- Do not commit, push or change Jira without being asked.
- If a Jira task contradicts a security rule in AGENTS.md, say so before following the task.
