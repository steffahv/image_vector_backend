import json
import uuid

from pydantic import AwareDatetime, BaseModel, Field, JsonValue, field_validator


class JobRequest(BaseModel):
    type: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    idempotency_key: str = Field(min_length=1, max_length=200)
    workspace_id: uuid.UUID | None
    payload: dict[str, JsonValue] = Field(default_factory=dict)
    next_run_at: AwareDatetime | None = None

    @field_validator("payload")
    @classmethod
    def _bounded_json(cls, payload: dict[str, JsonValue]) -> dict[str, JsonValue]:
        if len(json.dumps(payload, allow_nan=False).encode()) > 16_384:
            raise ValueError("job payload exceeds 16 KiB")
        return payload
