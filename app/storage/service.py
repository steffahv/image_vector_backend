"""Business logic for storage.

What goes here:
- The S3 client (Cloudflare R2 in production) and signed URLs (10 min max).
- Checking uploads (size, format, dimensions, hash) and moving them to immutable keys.
- Quota reservation and release.

This is the only module that talks to S3. It knows files and quotas, not documents.
"""
