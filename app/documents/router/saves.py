import uuid

from fastapi import APIRouter, status

from app.core.not_implemented import not_implemented
from app.documents.router.responses import OWN, Responses, SignedIn
from app.documents.schemas import SaveConflictResponse, SaveCreate, SaveResponse

router = APIRouter(prefix="/documents")

CONFLICT: Responses = {
    status.HTTP_409_CONFLICT: {
        "model": SaveConflictResponse,
        "description": "Another revision was saved since base_revision. Nothing was overwritten.",
    }
}


@router.post(
    "/{document_id}/saves",
    status_code=status.HTTP_201_CREATED,
    response_model=SaveResponse,
    summary="Start saving a new revision",
    description=(
        "Checks the document, the base revision and the space, holds the space and returns a "
        "signed URL for each file to upload. Retrying with the same idempotency_key returns "
        "the same save (200), already confirmed if it was."
    ),
    responses=OWN
    | CONFLICT
    | {
        status.HTTP_200_OK: {"model": SaveResponse, "description": "A retry of a known save."},
        status.HTTP_507_INSUFFICIENT_STORAGE: {"description": "Not enough space left."},
    },
)
def create_save(document_id: uuid.UUID, body: SaveCreate, current: SignedIn) -> SaveResponse:
    not_implemented()


@router.get(
    "/{document_id}/saves/{save_id}",
    response_model=SaveResponse,
    summary="Get the state of a save",
    responses=OWN,
)
def read_save(document_id: uuid.UUID, save_id: uuid.UUID, current: SignedIn) -> SaveResponse:
    not_implemented()


@router.post(
    "/{document_id}/saves/{save_id}/commit",
    response_model=SaveResponse,
    summary="Publish a save once its files are uploaded",
    description=(
        "Checks size, format, dimensions, hash and JSON of every uploaded file, then makes "
        "the new revision current in one transaction. Only after this answers is the document "
        "saved. Safe to repeat."
    ),
    responses=OWN
    | CONFLICT
    | {
        status.HTTP_422_UNPROCESSABLE_ENTITY: {
            "description": "A file is missing or does not match what was declared."
        }
    },
)
def commit_save(document_id: uuid.UUID, save_id: uuid.UUID, current: SignedIn) -> SaveResponse:
    not_implemented()
