from pydantic import BaseModel, Field


class QuotaResponse(BaseModel):
    """Space of the account's workspace, in bytes."""

    limit_bytes: int
    used_bytes: int = Field(description="May pass the limit after a plan downgrade.")
    reserved_bytes: int = Field(description="Held by saves still uploading.")
