import uuid

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse

from app.core.not_implemented import not_implemented
from app.documents import service
from app.documents.router.responses import MINE, OWN, Db, SignedIn, not_found
from app.documents.router.saves import CONFLICT
from app.documents.schemas import (
    VersionCreate,
    VersionResponse,
    VersionRestore,
    VersionRestoreResponse,
)
from app.documents.schemas.save import SaveConflictResponse

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
    description=(
        "Publishes the version's revision again as the next revision: the number always goes "
        "up. The revision that was current is kept as a `restore` version (undo_version_id)."
    ),
    responses=MINE | CONFLICT,
)
def restore_version(
    document_id: uuid.UUID,
    version_id: uuid.UUID,
    body: VersionRestore,
    current: SignedIn,
    db: Db,
) -> VersionRestoreResponse | JSONResponse:
    try:
        return service.restore_version(
            db, current.account_id, document_id, version_id, body.base_revision
        )
    except (service.DocumentNotFound, service.VersionNotFound):
        raise not_found() from None
    except service.RestoreConflict as conflict:
        answer = SaveConflictResponse(
            detail="Another revision was saved meanwhile. Nothing was changed.",
            current_revision=conflict.current_revision,
        )
        return JSONResponse(answer.model_dump(), status_code=status.HTTP_409_CONFLICT)
    except service.VersionUnavailable:
        raise HTTPException(
            status.HTTP_409_CONFLICT, detail="This version can no longer be restored."
        ) from None
