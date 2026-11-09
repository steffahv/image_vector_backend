"""Response models for the health API."""

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str
    service: str
