import uuid
from typing import Annotated

from fastapi import APIRouter, Query, status

from app.core.not_implemented import not_implemented
from app.documents.models import DocumentStatus
from app.documents.router.responses import OWN, SignedIn
from app.documents.schemas import (
    PAGE_MAX_SIZE,
    SEARCH_MAX_LENGTH,
    DocumentCreate,
    DocumentDuplicate,
    DocumentPage,
    DocumentResponse,
    DocumentUpdate,
)

router = APIRouter(prefix="/documents")


@router.get("", response_model=DocumentPage, summary="List and search documents", responses=OWN)
def list_documents(
    current: SignedIn,
    status_: Annotated[DocumentStatus | None, Query(alias="status")] = None,
    folder_id: uuid.UUID | None = None,
    q: Annotated[str | None, Query(max_length=SEARCH_MAX_LENGTH)] = None,
    cursor: Annotated[str | None, Query(max_length=200)] = None,
    limit: Annotated[int, Query(ge=1, le=PAGE_MAX_SIZE)] = 50,
) -> DocumentPage:
    not_implemented()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentResponse,
    summary="Create an empty document",
    responses=OWN,
)
def create_document(body: DocumentCreate, current: SignedIn) -> DocumentResponse:
    not_implemented()


@router.get(
    "/{document_id}", response_model=DocumentResponse, summary="Get a document", responses=OWN
)
def read_document(document_id: uuid.UUID, current: SignedIn) -> DocumentResponse:
    not_implemented()


@router.patch(
    "/{document_id}",
    response_model=DocumentResponse,
    summary="Rename a document or move it to another folder",
    responses=OWN,
)
def update_document(
    document_id: uuid.UUID, body: DocumentUpdate, current: SignedIn
) -> DocumentResponse:
    not_implemented()


@router.post(
    "/{document_id}/duplicate",
    status_code=status.HTTP_201_CREATED,
    response_model=DocumentResponse,
    summary="Duplicate a document at its current revision",
    responses=OWN,
)
def duplicate_document(
    document_id: uuid.UUID, body: DocumentDuplicate, current: SignedIn
) -> DocumentResponse:
    not_implemented()


@router.post(
    "/{document_id}/trash",
    response_model=DocumentResponse,
    summary="Move a document to the trash",
    description="It is deleted for good 30 days later. Safe to repeat.",
    responses=OWN,
)
def trash_document(document_id: uuid.UUID, current: SignedIn) -> DocumentResponse:
    not_implemented()


@router.post(
    "/{document_id}/restore",
    response_model=DocumentResponse,
    summary="Take a document out of the trash",
    responses=OWN,
)
def restore_document(document_id: uuid.UUID, current: SignedIn) -> DocumentResponse:
    not_implemented()
