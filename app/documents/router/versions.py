import uuid

from fastapi import APIRouter, status

from app.core.not_implemented import not_implemented
from app.documents.router.responses import OWN, SignedIn
from app.documents.router.saves import CONFLICT
from app.documents.schemas import (
    VersionCreate,
    VersionResponse,
    VersionRestore,
    VersionRestoreResponse,
)

router = APIRouter(prefix="/documents")


@router.get(
    "/{document_id}/versions",
    response_model=list[VersionResponse],
    summary="List the versions of a document",
    responses=OWN,
)
def list_versions(document_id: uuid.UUID, current: SignedIn) -> list[VersionResponse]:
    not_implemented()


@router.post(
    "/{document_id}/versions",
    status_code=status.HTTP_201_CREATED,
    response_model=VersionResponse,
    summary="Keep the current revision as a version",
    description="Past the plan's limit, the oldest unprotected versions are dropped.",
    responses=OWN,
)
def create_version(
    document_id: uuid.UUID, body: VersionCreate, current: SignedIn
) -> VersionResponse:
    not_implemented()


@router.post(
    "/{document_id}/versions/{version_id}/restore",
    response_model=VersionRestoreResponse,
    summary="Restore a version as a new revision",
    responses=OWN | CONFLICT,
)
def restore_version(
    document_id: uuid.UUID, version_id: uuid.UUID, body: VersionRestore, current: SignedIn
) -> VersionRestoreResponse:
    not_implemented()
