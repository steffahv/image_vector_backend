"""Dependencies and error responses shared by the documents routes.

Swagger documents the errors the same way on every route.
"""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.auth.service import CurrentUser, get_current_user
from app.core.db import get_db
from app.core.not_implemented import NOT_IMPLEMENTED_RESPONSE
from app.storage.service import ObjectStore, StorageUnavailable, get_object_store

SignedIn = Annotated[CurrentUser, Depends(get_current_user)]
Db = Annotated[Session, Depends(get_db)]

Responses = dict[int | str, dict[str, Any]]

NOT_SIGNED_IN: Responses = {status.HTTP_401_UNAUTHORIZED: {"description": "Not signed in."}}
# 404, never 403: a document of another account must not even be confirmed to exist.
NOT_FOUND: Responses = {status.HTTP_404_NOT_FOUND: {"description": "Not found in your account."}}
STORAGE_UNAVAILABLE: Responses = {
    status.HTTP_503_SERVICE_UNAVAILABLE: {"description": "File storage is not available."}
}
MINE = NOT_SIGNED_IN | NOT_FOUND
OWN = MINE | NOT_IMPLEMENTED_RESPONSE


def object_store() -> ObjectStore:
    try:
        return get_object_store()
    except StorageUnavailable:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="File storage is not available."
        ) from None


Store = Annotated[ObjectStore, Depends(object_store)]


def not_found() -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, detail="Not found.")
