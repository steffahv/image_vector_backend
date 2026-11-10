import uuid
from collections.abc import Callable
from dataclasses import dataclass

from pydantic import JsonValue
from sqlalchemy.orm import Session


@dataclass(frozen=True)
class JobContext:
    id: uuid.UUID
    workspace_id: uuid.UUID | None
    payload: dict[str, JsonValue]


JobHandler = Callable[[Session, JobContext], None]
