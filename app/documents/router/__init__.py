"""HTTP routes for documents.

What goes here:
- documents.py: create, list, search, rename, move, duplicate, trash and restore documents.
- saves.py: save a new revision (VEC-31).
- content.py: open a document (VEC-42).
- versions.py: versions and restoring them (VEC-43).
- folders.py: folders (VEC-43).
- share_links.py: share links, and reading a shared document without an account (VEC-43).
- responses.py: error responses and the signed-in dependency shared by these routes.

The contracts are published before the logic (they answer 501), so the editor can be built
against Swagger in parallel.

Rules:
- Receive the request, validate it with schemas/ and call service/. Nothing else.
- No database queries and no business rules here.
- Declare response_model and a short summary on every route so Swagger documents it.
"""

from fastapi import APIRouter

from app.documents.router import content, documents, folders, saves, share_links, versions

router = APIRouter(tags=["documents"])
for module in (documents, saves, content, versions, folders, share_links):
    router.include_router(module.router)
