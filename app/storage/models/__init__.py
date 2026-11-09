"""SQLAlchemy tables for storage, in the `storage` PostgreSQL schema (VEC-29).

One file per table. See Modelo_relacional_VectorEdit §V and docs/base-de-datos.md.

- stored_object.py: `objects` (StoredObject), metadata and location of every file.
- document_save.py: `saves` (DocumentSave), idempotent save requests.
- upload.py: `uploads` (Upload), uploads to storage with a signed URL.
- workspace_quota.py: `workspace_quotas` (WorkspaceQuota), space limit and usage.
- byte_reservation.py: `byte_reservations` (ByteReservation), space held by an upload.

Import every table here: Alembic and other modules import from `app.storage.models`.
"""

from app.storage.models.byte_reservation import ByteReservation, ByteReservationStatus
from app.storage.models.document_save import DocumentSave, SaveStatus
from app.storage.models.stored_object import (
    ObjectEncoding,
    ObjectKind,
    ObjectStatus,
    StoredObject,
)
from app.storage.models.upload import Upload, UploadStatus
from app.storage.models.workspace_quota import WorkspaceQuota

__all__ = [
    "ByteReservation",
    "ByteReservationStatus",
    "DocumentSave",
    "ObjectEncoding",
    "ObjectKind",
    "ObjectStatus",
    "SaveStatus",
    "StoredObject",
    "Upload",
    "UploadStatus",
    "WorkspaceQuota",
]
