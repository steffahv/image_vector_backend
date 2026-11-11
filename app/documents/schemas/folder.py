import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.documents.schemas.document import Name


class FolderCreate(BaseModel):
    name: Name
    parent_id: uuid.UUID | None = Field(default=None, description="Null for the top level.")


class FolderUpdate(BaseModel):
    """Rename or move a folder. A folder cannot be moved inside itself or its subfolders."""

    name: Name | None = None
    parent_id: uuid.UUID | None = None
    move_to_root: bool = Field(
        default=False, description="Move it to the top level (parent_id is ignored)."
    )


class FolderResponse(BaseModel):
    id: uuid.UUID
    workspace_id: uuid.UUID
    parent_id: uuid.UUID | None
    name: str
    created_at: datetime
    updated_at: datetime
