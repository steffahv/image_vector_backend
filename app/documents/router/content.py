import uuid

from fastapi import APIRouter

from app.core.not_implemented import not_implemented
from app.documents.router.responses import OWN, SignedIn
from app.documents.schemas import DocumentContentResponse

router = APIRouter(prefix="/documents")


@router.get(
    "/{document_id}/content",
    response_model=DocumentContentResponse,
    summary="Open a document",
    description=(
        "Signed URLs to the JSON, thumbnail and images of the current revision, valid for 10 "
        "minutes. The editor downloads the files straight from storage."
    ),
    responses=OWN,
)
def open_document(document_id: uuid.UUID, current: SignedIn) -> DocumentContentResponse:
    not_implemented()
