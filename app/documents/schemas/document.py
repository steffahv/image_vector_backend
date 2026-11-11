import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.documents.models import DocumentSource, DocumentStatus

NAME_MAX_LENGTH = 200
FORMAT_MAX_LENGTH = 50
# Canvas side in points. Large enough for any print format, small enough to stay sane.
MAX_SIDE = 100_000.0
PAGE_MAX_SIZE = 100
SEARCH_MAX_LENGTH = 200

Name = Annotated[str, Field(min_length=1, max_length=NAME_MAX_LENGTH)]
Side = Annotated[float, Field(gt=0, le=MAX_SIDE, allow_inf_nan=False)]


class DocumentCreate(BaseModel):
    """A new, empty document. It stays a draft until its first save."""

    name: Name
    format: Annotated[str, Field(min_length=1, max_length=FORMAT_MAX_LENGTH, examples=["a4"])]
    width: Side
    height: Side
    folder_id: uuid.UUID | None = None
    source: DocumentSource = DocumentSource.BLANK


class DocumentUpdate(BaseModel):
    """Rename a document or move it to another folder. Fields left out do not change."""

    name: Name | None = None
    folder_id: uuid.UUID | None = None
    move_to_root: bool = Field(
        default=False, description="Take the document out of its folder (folder_id is ignored)."
    )


class DocumentDuplicate(BaseModel):
    name: Name | None = Field(default=None, description="Defaults to the original name + copy.")


class DocumentResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    folder_id: uuid.UUID | None
    name: str
    format: str
    width: float
    height: float
    current_revision: int | None = Field(description="Null while the document is a draft.")
    source: DocumentSource
    status: DocumentStatus
    deleted_at: datetime | None = Field(description="When it went to the trash.")
    created_at: datetime
    updated_at: datetime


class DocumentPage(BaseModel):
    items: list[DocumentResponse]
    next_cursor: str | None = Field(description="Pass it as `cursor` to get the next page.")
