"""HTTP routes for storage.

What goes here:
- Request signed URLs to upload or download files.
- Confirm an upload so it can be checked.
- Read the current quota usage.

Rules:
- Receive the request, validate it with schemas.py and call service.py. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.
"""

from fastapi import APIRouter

router = APIRouter(prefix="/storage", tags=["storage"])
