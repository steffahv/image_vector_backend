"""Business logic for documents.

What goes here:
- Ownership and permission checks for every document operation.
- Transactional save: lock in a fixed order (quota, document, files), check the base
  revision, insert the new revision, move the head and update counters (VEC-31).
- Opening documents (VEC-42), folders, versions, trash and sharing (VEC-43).

Uses storage/service.py for files and quotas; never touches S3 directly.
"""
