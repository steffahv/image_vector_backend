"""The save flow (Arquitectura §III-A): prepare, upload to signed URLs, then commit."""

import uuid
from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field

from app.storage.models import SaveStatus

# Largest file of each kind the platform accepts. Checked again on the uploaded bytes.
MAX_DOCUMENT_JSON_BYTES = 50 * 1024 * 1024
MAX_IMAGE_BYTES = 25 * 1024 * 1024
MAX_THUMBNAIL_BYTES = 2 * 1024 * 1024
MAX_IMAGES_PER_SAVE = 500
EDITOR_HASH_MAX_LENGTH = 128
MAX_IMAGE_SIDE = 20_000

Sha256Hex = Annotated[
    str,
    Field(
        pattern=r"^[0-9a-f]{64}$",
        description="SHA-256 of the exact bytes to upload, in lowercase hex.",
    ),
]
ImageSide = Annotated[int, Field(gt=0, le=MAX_IMAGE_SIDE)]


class SavedFile(BaseModel):
    """A file of the save, described before it is uploaded. The platform checks it after."""

    sha256: Sha256Hex
    size_bytes: Annotated[int, Field(gt=0)]
    mime_type: Annotated[str, Field(min_length=1, max_length=100, examples=["image/png"])]


class DocumentJsonFile(SavedFile):
    size_bytes: Annotated[int, Field(gt=0, le=MAX_DOCUMENT_JSON_BYTES)]
    gzip: bool = Field(default=True, description="Whether the JSON is uploaded gzip-compressed.")
    original_bytes: Annotated[int, Field(gt=0, description="Size of the uncompressed JSON.")]
    format_version: Annotated[int, Field(gt=0)]


class ThumbnailFile(SavedFile):
    size_bytes: Annotated[int, Field(gt=0, le=MAX_THUMBNAIL_BYTES)]
    width: ImageSide
    height: ImageSide


class ImageFile(SavedFile):
    editor_hash: Annotated[
        str,
        Field(
            min_length=1,
            max_length=EDITOR_HASH_MAX_LENGTH,
            description="How the document JSON refers to this image.",
        ),
    ]
    size_bytes: Annotated[int, Field(gt=0, le=MAX_IMAGE_BYTES)]
    width: ImageSide
    height: ImageSide


class SaveCreate(BaseModel):
    """Ask to save a new revision of the document."""

    idempotency_key: uuid.UUID = Field(
        description="New for each save attempt, the same when retrying it. A retry returns the "
        "save already made instead of making another."
    )
    base_revision: Annotated[
        int,
        Field(ge=0, description="The revision the editor worked on; 0 for a never-saved draft."),
    ]
    document: DocumentJsonFile
    thumbnail: ThumbnailFile | None = None
    images: Annotated[list[ImageFile], Field(max_length=MAX_IMAGES_PER_SAVE)] = []


class UploadRole(StrEnum):
    DOCUMENT = "document"
    THUMBNAIL = "thumbnail"
    IMAGE = "image"


class UploadTarget(BaseModel):
    """Where to upload one file: a signed URL valid for one PUT, for 10 minutes at most."""

    upload_id: uuid.UUID
    role: UploadRole
    editor_hash: str | None = Field(description="Set for images.")
    method: str = Field(examples=["PUT"])
    url: str
    headers: dict[str, str] = Field(description="Send them exactly as given with the upload.")
    expires_at: datetime


class SaveResponse(BaseModel):
    id: uuid.UUID
    document_id: uuid.UUID
    status: SaveStatus
    base_revision: int
    revision: int | None = Field(description="The new revision, once the save is confirmed.")
    uploads: list[UploadTarget] = Field(
        description="Files still to upload. Images already stored in the workspace are not "
        "uploaded again."
    )
    expires_at: datetime


class SaveConflictResponse(BaseModel):
    """409: someone saved another revision since `base_revision`. Nothing was overwritten."""

    detail: str
    current_revision: int
