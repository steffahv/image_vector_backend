import uuid
from typing import Annotated

from fastapi import APIRouter, Path, Response, status

from app.core.not_implemented import NOT_IMPLEMENTED_RESPONSE, not_implemented
from app.documents.router.responses import NOT_FOUND, OWN, SignedIn
from app.documents.schemas import (
    SharedDocumentResponse,
    ShareLinkCreate,
    ShareLinkCreatedResponse,
    ShareLinkResponse,
)

router = APIRouter()

# Share tokens are random and short; anything longer is not one of ours.
TOKEN_MAX_LENGTH = 100


@router.post(
    "/documents/{document_id}/share-links",
    status_code=status.HTTP_201_CREATED,
    response_model=ShareLinkCreatedResponse,
    summary="Create a read-only share link",
    responses=OWN,
)
def create_share_link(
    document_id: uuid.UUID, body: ShareLinkCreate, current: SignedIn
) -> ShareLinkCreatedResponse:
    not_implemented()


@router.get(
    "/documents/{document_id}/share-links",
    response_model=list[ShareLinkResponse],
    summary="List the share links of a document",
    responses=OWN,
)
def list_share_links(document_id: uuid.UUID, current: SignedIn) -> list[ShareLinkResponse]:
    not_implemented()


@router.delete(
    "/documents/{document_id}/share-links/{link_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Disable a share link",
    responses=OWN,
)
def disable_share_link(document_id: uuid.UUID, link_id: uuid.UUID, current: SignedIn) -> Response:
    not_implemented()


@router.get(
    "/shared/{token}",
    response_model=SharedDocumentResponse,
    summary="Read a shared document, without an account",
    description="Public and read-only. Disabled, expired and unknown links all answer 404.",
    responses=NOT_FOUND | NOT_IMPLEMENTED_RESPONSE,
)
def read_shared_document(
    token: Annotated[str, Path(min_length=1, max_length=TOKEN_MAX_LENGTH)],
) -> SharedDocumentResponse:
    not_implemented()
