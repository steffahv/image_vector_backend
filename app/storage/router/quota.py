from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.auth.service import CurrentUser, get_current_user
from app.core.not_implemented import NOT_IMPLEMENTED_RESPONSE, not_implemented
from app.storage.schemas import QuotaResponse

router = APIRouter()


@router.get(
    "/quota",
    response_model=QuotaResponse,
    summary="Get the space used and left",
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Not signed in."},
        **NOT_IMPLEMENTED_RESPONSE,
    },
)
def read_quota(current: Annotated[CurrentUser, Depends(get_current_user)]) -> QuotaResponse:
    not_implemented()
