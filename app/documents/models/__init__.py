"""SQLAlchemy tables for documents, in the `platform` PostgreSQL schema (VEC-29).

One file per table. See Modelo_relacional_VectorEdit §IV and docs/base-de-datos.md.

Tables:
- account.py: `accounts` (Account), the product account (needed by VEC-4).
- workspace.py: `workspaces` (Workspace), the space that owns everything else.
- folder.py: `folders` (Folder).
- document.py: `documents` (Document).
- document_revision.py: `document_revisions` (DocumentRevision), saved states.
- document_version.py: `document_versions` (DocumentVersion), kept history marks.
- revision_image.py: `revision_images` (RevisionImage), images used by each revision.
- share_link.py: `share_links` (ShareLink), public read-only links.

Import every table here: Alembic and other modules import from `app.documents.models`.
"""

from app.documents.models.account import Account, AgentMode
from app.documents.models.document import Document, DocumentSource, DocumentStatus
from app.documents.models.document_revision import DocumentRevision, RevisionAuthorType
from app.documents.models.document_version import DocumentVersion, VersionSource
from app.documents.models.folder import Folder
from app.documents.models.revision_image import RevisionImage
from app.documents.models.share_link import ShareLink
from app.documents.models.workspace import Workspace, WorkspaceType

__all__ = [
    "Account",
    "AgentMode",
    "Document",
    "DocumentRevision",
    "DocumentSource",
    "DocumentStatus",
    "DocumentVersion",
    "Folder",
    "RevisionAuthorType",
    "RevisionImage",
    "ShareLink",
    "VersionSource",
    "Workspace",
    "WorkspaceType",
]
