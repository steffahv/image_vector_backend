"""Error responses shared by the documents routes, so Swagger documents them the same way."""

from typing import Annotated, Any

from fastapi import Depends, status

from app.auth.service import CurrentUser, get_current_user
from app.core.not_implemented import NOT_IMPLEMENTED_RESPONSE

SignedIn = Annotated[CurrentUser, Depends(get_current_user)]

Responses = dict[int | str, dict[str, Any]]

NOT_SIGNED_IN: Responses = {status.HTTP_401_UNAUTHORIZED: {"description": "Not signed in."}}
# 404, never 403: a document of another account must not even be confirmed to exist.
NOT_FOUND: Responses = {status.HTTP_404_NOT_FOUND: {"description": "Not found in your account."}}
OWN = NOT_SIGNED_IN | NOT_FOUND | NOT_IMPLEMENTED_RESPONSE
