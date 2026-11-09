"""SQLAlchemy tables for documents, in the `platform` PostgreSQL schema (VEC-29).

One file per table. Planned: accounts, workspaces, folders, documents, document
revisions, revision images, document versions and share links.
See Modelo_relacional_VectorEdit §IV and docs/base-de-datos.md.

Done so far:
- account.py: `accounts` (Account), the product account (needed by VEC-4).

Import every table here: Alembic and other modules import from `app.documents.models`.
"""

from app.documents.models.account import Account, AgentMode

__all__ = ["Account", "AgentMode"]
