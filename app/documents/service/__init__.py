"""Business logic for documents.

What goes here:
- Ownership and permission checks for every document operation.
- Transactional save: lock in a fixed order (quota, document, files), check the base
  revision, insert the new revision, move the head and update counters (VEC-31).
- Opening documents (VEC-42), folders, versions, trash and sharing (VEC-43).

Uses `app.storage.service` for files and quotas; never touches S3 directly.

One file per use case, imported here so other code imports from `app.documents.service`:
- access.py: ownership checks and the fixed lock order (quota, document, files).
- accounts.py: the product account of a signed-in user (used by auth).
- save.py: the transactional save (VEC-31).
- revisions.py: publishing a revision and reading its files (save and restore).
- open.py: opening a document with signed URLs (VEC-42).
- versions.py: restoring a version as a new revision (VEC-42).
"""

from app.documents.service.access import DocumentNotFound
from app.documents.service.accounts import find_account_id, get_or_create_account
from app.documents.service.open import open_document
from app.documents.service.save import (
    IdempotencyKeyReused,
    SaveConflict,
    SaveExpired,
    SaveFilesMissing,
    SaveNotFound,
    SaveRejected,
    commit_save,
    create_save,
    read_save,
)
from app.documents.service.versions import (
    RestoreConflict,
    VersionNotFound,
    VersionUnavailable,
    restore_version,
)

__all__ = [
    "DocumentNotFound",
    "IdempotencyKeyReused",
    "RestoreConflict",
    "SaveConflict",
    "SaveExpired",
    "SaveFilesMissing",
    "SaveNotFound",
    "SaveRejected",
    "VersionNotFound",
    "VersionUnavailable",
    "commit_save",
    "create_save",
    "find_account_id",
    "get_or_create_account",
    "open_document",
    "read_save",
    "restore_version",
]
