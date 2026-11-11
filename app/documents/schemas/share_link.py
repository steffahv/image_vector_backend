import uuid
from datetime import datetime

from pydantic import AwareDatetime, BaseModel, Field

from app.documents.schemas.content import DocumentJson, RevisionImage, SignedFile


class ShareLinkCreate(BaseModel):
    allows_download: bool = False
    expires_at: AwareDatetime | None = Field(default=None, description="Null: until disabled.")


class ShareLinkResponse(BaseModel):
    """A share link as listed later. The token is never shown again: only its hash is stored."""

    id: uuid.UUID
    document_id: uuid.UUID
    active: bool
    allows_download: bool
    expires_at: datetime | None
    created_at: datetime


class ShareLinkCreatedResponse(ShareLinkResponse):
    token: str = Field(description="Shown only in this response. The read-only link uses it.")


class SharedDocumentResponse(BaseModel):
    """A shared document, read without an account. Read-only: there is no way to change it."""

    name: str
    width: float
    height: float
    revision: int
    allows_download: bool
    document: DocumentJson
    thumbnail: SignedFile | None
    images: list[RevisionImage]
