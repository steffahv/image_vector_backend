import uuid
from enum import StrEnum

from sqlalchemy import ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum


class AuditResult(StrEnum):
    """How an audited action ended."""

    SUCCESS = "success"
    DENIED = "denied"
    ERROR = "error"


class AuditEntry(UUIDPrimaryKey, CreatedAt, Base):
    """One security-relevant action. Append-only: nobody updates or deletes entries.

    The actor and the entity are historical references with no foreign key, so recording an
    action never blocks deleting the data it was about (§VIII). `actor_ref` is an opaque id,
    never an email or a name.

    Write entries with `db.execute(insert(AuditEntry).values(...))`, not `db.add()`. Entries are
    often written with no account set (a failed sign-in), and such a session may add an entry
    but not read it back, and RETURNING counts as reading. So the table never asks for RETURNING
    on its own (`implicit_returning=False`); `db.add()` fails because it needs the new id.
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        Index(None, "workspace_id"),
        Index(None, "created_at"),
        {"schema": DbSchema.OPERATIONS, "implicit_returning": False},
    )

    actor_ref: Mapped[str | None]
    # SET NULL: the workspace can be deleted and the entry kept without its context (§IX-C).
    workspace_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("platform.workspaces.id", ondelete="SET NULL")
    )
    action: Mapped[str]
    entity_type: Mapped[str]
    entity_id: Mapped[str | None]
    result: Mapped[AuditResult] = mapped_column(text_enum(AuditResult, "result"))
