import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field

from app.documents.models import VersionSource

LABEL_MAX_LENGTH = 200


class VersionCreate(BaseModel):
    """Keep the current revision as a version.

    The editor sends `automatic` at most every 10 minutes of editing and when the tab closes
    with changes; `manual` when the user asks. The plan limits how many are kept.
    """

    source: Annotated[VersionSource, Field(examples=[VersionSource.MANUAL])]
    label: Annotated[str, Field(min_length=1, max_length=LABEL_MAX_LENGTH)] | None = None


class VersionRestore(BaseModel):
    """Restore a version: publishes it as a new revision, so the number always goes up."""

    base_revision: Annotated[
        int, Field(ge=1, description="The revision on screen; 409 if another was saved since.")
    ]


class VersionResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    revision: int
    source: VersionSource
    label: str | None
    protected_until: datetime | None
    created_at: datetime


class VersionRestoreResponse(BaseModel):
    revision: int = Field(description="The new current revision, a copy of the restored one.")
    undo_version_id: uuid.UUID = Field(
        description="Version kept of the revision that was current before. Restoring it undoes "
        "the restore."
    )
