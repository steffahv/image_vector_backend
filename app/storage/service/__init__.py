"""Business logic for storage.

What goes here:
- The S3-compatible client and signed URLs (10 min max).
- Checking uploads (size, format, dimensions, hash) and moving them to immutable keys.
- Quota reservation and release.

This is the only module that talks to S3. It knows files and quotas, not documents.

How to split: one file per use case (e.g. `save.py`, `open.py`) in this folder,
imported here so other code keeps importing from `app.storage.service`.
`app/auth/models/` is an example.
"""
