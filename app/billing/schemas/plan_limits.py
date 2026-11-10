from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field


class PlanLimits(BaseModel):
    """The part of the entitlement contract used by document retention."""

    model_config = ConfigDict(extra="allow")

    max_versions: Annotated[int, Field(strict=True, gt=0, le=2_147_483_647)]
