"""Business logic for documents.

What goes here:
- Ownership and permission checks for every document operation.
- Transactional save: lock in a fixed order (quota, document, files), check the base
  revision, insert the new revision, move the head and update counters (VEC-31).
- Opening documents (VEC-42), folders, versions, trash and sharing (VEC-43).

Uses `app.storage.service` for files and quotas; never touches S3 directly.

How to split: one file per use case (e.g. `save.py`, `open.py`) in this folder,
imported here so other code keeps importing from `app.documents.service`.
`app/auth/models/` is an example.
"""

from app.documents.service.accounts import find_account_id, get_or_create_account

__all__ = ["find_account_id", "get_or_create_account"]
