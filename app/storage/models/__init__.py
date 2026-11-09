"""SQLAlchemy tables for storage, in the `storage` PostgreSQL schema (VEC-29).

One file per table. See Modelo_relacional_VectorEdit §V and docs/base-de-datos.md.

Done so far:
- stored_object.py: `objects` (StoredObject), metadata and location of every file.

Still planned: uploads, saves, workspace quotas and byte reservations.

Import every table here: Alembic and other modules import from `app.storage.models`.
"""

from app.storage.models.stored_object import (
    ObjectEncoding,
    ObjectKind,
    ObjectStatus,
    StoredObject,
)

__all__ = ["ObjectEncoding", "ObjectKind", "ObjectStatus", "StoredObject"]
