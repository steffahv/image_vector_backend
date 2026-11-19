import uuid
from collections.abc import Iterator
from contextlib import contextmanager

from fastapi import APIRouter, HTTPException, Response, status
from fastapi.responses import JSONResponse

from app.documents import service
from app.documents.router.responses import (
    MINE,
    STORAGE_UNAVAILABLE,
    Db,
    Responses,
    SignedIn,
    Store,
    not_found,
)
from app.documents.schemas import SaveConflictResponse, SaveCreate, SaveResponse
from app.storage.service import InsufficientStorage, ObjectStoreError

router = APIRouter(prefix="/documents")

CONFLICT: Responses = {
    status.HTTP_409_CONFLICT: {
        "model": SaveConflictResponse,
        "description": "Another revision was saved since base_revision. Nothing was overwritten.",
    }
}
GONE: Responses = {
    status.HTTP_410_GONE: {"description": "The save expired before it was committed. Start again."}
}
INVALID: Responses = {
    status.HTTP_422_UNPROCESSABLE_CONTENT: {
        "description": "Invalid request, or the idempotency key was used for another request."
    }
}


@contextmanager
def _answers() -> Iterator[None]:
    """Turn the save errors into HTTP answers. Details never include keys, URLs or SQL.

    A conflict is answered by each route with its body (`_conflict_response`).
    """
    try:
        yield
    except (service.DocumentNotFound, service.SaveNotFound):
        raise not_found() from None
    except service.IdempotencyKeyReused:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="This idempotency_key was already used for a different save.",
        ) from None
    except InsufficientStorage:
        raise HTTPException(
            status.HTTP_507_INSUFFICIENT_STORAGE, detail="Not enough storage space left."
        ) from None
    except service.SaveFilesMissing:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Some files are not uploaded yet. Upload them and commit again.",
        ) from None
    except service.SaveRejected as rejected:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=rejected.reason) from None
    except service.SaveExpired:
        raise HTTPException(status.HTTP_410_GONE, detail="The save expired. Start again.") from None
    except ObjectStoreError:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="File storage is not available."
        ) from None


def _conflict_response(conflict: service.SaveConflict) -> JSONResponse:
    body = SaveConflictResponse(
        detail="Another revision was saved meanwhile. Nothing was overwritten.",
        current_revision=conflict.current_revision,
    )
    return JSONResponse(body.model_dump(), status_code=status.HTTP_409_CONFLICT)


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
    responses=MINE
    | CONFLICT
    | INVALID
    | STORAGE_UNAVAILABLE
    | {
        status.HTTP_200_OK: {"model": SaveResponse, "description": "A retry of a known save."},
        status.HTTP_507_INSUFFICIENT_STORAGE: {"description": "Not enough space left."},
    },
)
def create_save(
    document_id: uuid.UUID,
    body: SaveCreate,
    current: SignedIn,
    db: Db,
    store: Store,
    response: Response,
) -> SaveResponse | JSONResponse:
    try:
        with _answers():
            save, created = service.create_save(db, store, current.account_id, document_id, body)
    except service.SaveConflict as conflict:
        return _conflict_response(conflict)
    if not created:
        response.status_code = status.HTTP_200_OK
    return save


@router.get(
    "/{document_id}/saves/{save_id}",
    response_model=SaveResponse,
    summary="Get the state of a save",
    description="Files still to upload come with fresh signed URLs.",
    responses=MINE | STORAGE_UNAVAILABLE,
)
def read_save(
    document_id: uuid.UUID, save_id: uuid.UUID, current: SignedIn, db: Db, store: Store
) -> SaveResponse:
    with _answers():
        return service.read_save(db, store, current.account_id, document_id, save_id)


@router.post(
    "/{document_id}/saves/{save_id}/commit",
    response_model=SaveResponse,
    summary="Publish a save once its files are uploaded",
    description=(
        "Checks size, format, dimensions, hash and JSON of every uploaded file, then makes "
        "the new revision current in one transaction. Only a `confirmed` answer means the "
        "document is saved; `preparing` means another commit of this save is still checking "
        "files, so ask again. Safe to repeat."
    ),
    responses=MINE
    | CONFLICT
    | GONE
    | STORAGE_UNAVAILABLE
    | {
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "description": "A file is missing (upload it and commit again) or does not match "
            "what was declared (start a new save)."
        }
    },
)
def commit_save(
    document_id: uuid.UUID, save_id: uuid.UUID, current: SignedIn, db: Db, store: Store
) -> SaveResponse | JSONResponse:
    try:
        with _answers():
            return service.commit_save(db, store, current.account_id, document_id, save_id)
    except service.SaveConflict as conflict:
        return _conflict_response(conflict)
