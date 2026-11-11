import uuid

from fastapi import APIRouter, Response, status

from app.core.not_implemented import not_implemented
from app.documents.router.responses import OWN, SignedIn
from app.documents.schemas import FolderCreate, FolderResponse, FolderUpdate

router = APIRouter(prefix="/folders")


@router.get(
    "",
    response_model=list[FolderResponse],
    summary="List the folders inside a folder",
    description="Without parent_id, the top-level folders.",
    responses=OWN,
)
def list_folders(current: SignedIn, parent_id: uuid.UUID | None = None) -> list[FolderResponse]:
    not_implemented()


@router.post(
    "",
    status_code=status.HTTP_201_CREATED,
    response_model=FolderResponse,
    summary="Create a folder",
    responses=OWN,
)
def create_folder(body: FolderCreate, current: SignedIn) -> FolderResponse:
    not_implemented()


@router.patch(
    "/{folder_id}",
    response_model=FolderResponse,
    summary="Rename or move a folder",
    responses=OWN | {status.HTTP_409_CONFLICT: {"description": "It would end up inside itself."}},
)
def update_folder(folder_id: uuid.UUID, body: FolderUpdate, current: SignedIn) -> FolderResponse:
    not_implemented()


@router.delete(
    "/{folder_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    response_class=Response,
    summary="Delete an empty folder",
    responses=OWN | {status.HTTP_409_CONFLICT: {"description": "The folder is not empty."}},
)
def delete_folder(folder_id: uuid.UUID, current: SignedIn) -> Response:
    not_implemented()
