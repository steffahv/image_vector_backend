"""Opening a document (Arquitectura §III-B): signed URLs to its files, never the files."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class SignedFile(BaseModel):
    """A file to download with one GET, valid for 10 minutes at most."""

    url: str
    expires_at: datetime
    sha256: str = Field(description="SHA-256 of the stored bytes, in lowercase hex.")
    size_bytes: int
    mime_type: str


class DocumentJson(SignedFile):
    gzip: bool = Field(description="Whether the stored bytes are gzip-compressed.")
    format_version: int


class RevisionImage(SignedFile):
    editor_hash: str = Field(description="How the document JSON refers to this image.")


class DocumentContentResponse(BaseModel):
    """What the editor needs to open a revision.

    `account_id` and `workspace_id` let the editor keep its offline cache apart per account.
    """

    document_id: uuid.UUID
    workspace_id: uuid.UUID
    account_id: uuid.UUID
    revision: int | None = Field(description="Null for a draft that was never saved.")
    document: DocumentJson | None
    thumbnail: SignedFile | None
    images: list[RevisionImage]
