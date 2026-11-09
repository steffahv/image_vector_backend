"""OpenAPI (Swagger) metadata.

What goes here:
- The API title, description and version shown in /docs.
- One entry in `TAGS_METADATA` per module. The tag name must match the `tags`
  used in that module's APIRouter so its routes are grouped under it.
"""

API_TITLE = "Image Vector Backend"
API_VERSION = "0.1.0"
API_DESCRIPTION = """
Platform backend for VectorEdit: accounts, documents, files and billing.

The design agent is a separate TypeScript service and is not part of this API.
"""

TAGS_METADATA = [
    {"name": "health", "description": "Service liveness check."},
    {"name": "auth", "description": "Sign up, sign in (email and Google) and sessions."},
    {
        "name": "documents",
        "description": "Documents, revisions, versions, folders, trash and sharing.",
    },
    {"name": "storage", "description": "Signed upload/download URLs, file checks and quotas."},
    {"name": "billing", "description": "Plans, payments and credits (after launch)."},
]
