"""Pydantic request and response models for the documents API.

What goes here: document, revision, version, folder and share bodies and responses,
including the save request (base revision + idempotency key) and the 409 conflict response.
Every input has limits: text length, number ranges, list sizes and file sizes.

One file per topic:
- document.py: create, rename, move, duplicate and list documents.
- save.py: the save flow (VEC-31).
- content.py: opening a document with signed URLs (VEC-42).
- version.py: versions and restoring them (VEC-43).
- folder.py: folders (VEC-43).
- share_link.py: share links and reading a shared document without an account (VEC-43).
"""

from app.documents.schemas.content import (
    DocumentContentResponse,
    DocumentJson,
    RevisionImage,
    SignedFile,
)
from app.documents.schemas.document import (
    PAGE_MAX_SIZE,
    SEARCH_MAX_LENGTH,
    DocumentCreate,
    DocumentDuplicate,
    DocumentPage,
    DocumentResponse,
    DocumentUpdate,
)
from app.documents.schemas.folder import FolderCreate, FolderResponse, FolderUpdate
from app.documents.schemas.save import (
    DocumentJsonFile,
    ImageFile,
    SaveConflictResponse,
    SaveCreate,
    SaveResponse,
    ThumbnailFile,
    UploadRole,
    UploadTarget,
)
from app.documents.schemas.share_link import (
    SharedDocumentResponse,
    ShareLinkCreate,
    ShareLinkCreatedResponse,
    ShareLinkResponse,
)
from app.documents.schemas.version import (
    VersionCreate,
    VersionResponse,
    VersionRestore,
    VersionRestoreResponse,
)

__all__ = [
    "PAGE_MAX_SIZE",
    "SEARCH_MAX_LENGTH",
    "DocumentContentResponse",
    "DocumentCreate",
    "DocumentDuplicate",
    "DocumentJson",
    "DocumentJsonFile",
    "DocumentPage",
    "DocumentResponse",
    "DocumentUpdate",
    "FolderCreate",
    "FolderResponse",
    "FolderUpdate",
    "ImageFile",
    "RevisionImage",
    "SaveConflictResponse",
    "SaveCreate",
    "SaveResponse",
    "ShareLinkCreate",
    "ShareLinkCreatedResponse",
    "ShareLinkResponse",
    "SharedDocumentResponse",
    "SignedFile",
    "ThumbnailFile",
    "UploadRole",
    "UploadTarget",
    "VersionCreate",
    "VersionResponse",
    "VersionRestore",
    "VersionRestoreResponse",
]
