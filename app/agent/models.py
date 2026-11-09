"""SQLAlchemy tables for the agent, in the `agent` PostgreSQL schema (VEC-41).

What goes here: conversations, messages, runs, pending calls, period quotas, reservations,
rates and usage. See Modelo_relacional_VectorEdit §VII.

The agent service (TypeScript) writes these tables with its own database role.
This repo only defines them so Alembic stays the single migrator. No router or service here.
"""
