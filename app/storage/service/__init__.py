"""Business logic for storage.

What goes here:
- The S3-compatible client and signed URLs (10 min max).
- Checking uploads (size, format, dimensions, hash) and moving them to immutable keys.
- Quota reservation and release.

This is the only module that talks to S3. It knows files and quotas, not documents.

One file per use case, imported here so other code imports from `app.storage.service`:
- object_store.py: the S3-compatible bucket and signed URLs (the only file that talks to S3).
- file_checks.py: checking uploaded bytes against what was declared.
- quota.py: locking the workspace quota, holding and giving back space.
- saves.py: a save's request, uploads and reservations.
- objects.py: turning a checked upload into a stored file, reusing images, locking files.
- downloads.py: signed downloads of stored files (opening a document, VEC-42).
- maintenance.py: the cleanup the jobs queue runs (VEC-36).
"""

from app.storage.service.downloads import SignedDownload, sign_downloads
from app.storage.service.file_checks import ExpectedFile, FileRejected
from app.storage.service.maintenance import (
    delete_unused_objects,
    expire_uploads_and_reservations,
    reconcile_storage_quotas,
)
from app.storage.service.object_store import (
    MAX_SIGNED_URL_TTL,
    ObjectStore,
    ObjectStoreError,
    SignedUpload,
    StorageUnavailable,
    get_object_store,
)
from app.storage.service.objects import (
    ObjectUnavailable,
    UploadMissing,
    find_ready_images,
    lock_ready_objects,
    mark_referenced,
    store_upload,
    uploaded_objects,
)
from app.storage.service.quota import InsufficientStorage, QuotaMissing, lock_quota
from app.storage.service.saves import (
    NewSave,
    PlannedUpload,
    claim_uploads,
    confirm_save,
    end_save,
    find_save,
    get_save,
    has_open_uploads,
    open_save,
    save_uploads,
    sign_upload,
)

__all__ = [
    "MAX_SIGNED_URL_TTL",
    "ExpectedFile",
    "FileRejected",
    "InsufficientStorage",
    "NewSave",
    "ObjectStore",
    "ObjectStoreError",
    "ObjectUnavailable",
    "PlannedUpload",
    "QuotaMissing",
    "SignedDownload",
    "SignedUpload",
    "StorageUnavailable",
    "UploadMissing",
    "claim_uploads",
    "confirm_save",
    "delete_unused_objects",
    "end_save",
    "expire_uploads_and_reservations",
    "find_ready_images",
    "find_save",
    "get_object_store",
    "get_save",
    "has_open_uploads",
    "lock_quota",
    "lock_ready_objects",
    "mark_referenced",
    "open_save",
    "reconcile_storage_quotas",
    "save_uploads",
    "sign_downloads",
    "sign_upload",
    "store_upload",
    "uploaded_objects",
]
