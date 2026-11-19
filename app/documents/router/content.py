import uuid

from fastapi import APIRouter, HTTPException, status

from app.documents import service
from app.documents.router.responses import MINE, STORAGE_UNAVAILABLE, Db, SignedIn, Store, not_found
from app.documents.schemas import DocumentContentResponse
from app.storage.service import ObjectUnavailable

router = APIRouter(prefix="/documents")


@router.get(
    "/{document_id}/content",
    response_model=DocumentContentResponse,
    summary="Open a document",
    description=(
        "Signed URLs to the JSON, thumbnail and images of the current revision, valid for 10 "
        "minutes. The editor downloads the files straight from storage; ask again for new URLs "
        "once they expire. account_id and workspace_id are there to keep the offline cache "
        "apart per account."
    ),
    responses=MINE | STORAGE_UNAVAILABLE,
)
def open_document(
    document_id: uuid.UUID, current: SignedIn, db: Db, store: Store
) -> DocumentContentResponse:
    try:
        return service.open_document(db, store, current.account_id, document_id)
    except service.DocumentNotFound:
        raise not_found() from None
    except ObjectUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="A file of this document is not available."
        ) from None
