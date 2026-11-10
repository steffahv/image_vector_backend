import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, CheckConstraint, ForeignKeyConstraint, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey, text_enum
from app.documents.models import AgentMode


class RunStatus(StrEnum):
    """Lifecycle of a run (Modelo relacional §X). PENDING and RUNNING are the active ones."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class Run(UUIDPrimaryKey, CreatedAt, Base):
    """One turn of the agent on a document: from the request until it finishes or fails."""

    __tablename__ = "runs"
    __table_args__ = (
        # Lets reservations point to (account_id, id): a run of that same account.
        UniqueConstraint("account_id", "id"),
        # The conversation must be of the same account and workspace.
        ForeignKeyConstraint(
            ["account_id", "workspace_id", "conversation_id"],
            [
                "agent.conversations.account_id",
                "agent.conversations.workspace_id",
                "agent.conversations.id",
            ],
        ),
        ForeignKeyConstraint(
            ["workspace_id", "document_id"],
            ["platform.documents.workspace_id", "platform.documents.id"],
        ),
        # The version kept before the run must be of the same document. When versions are pruned
        # only this column is cleared; recorded_pre_agent_version_id keeps the evidence (§VII).
        ForeignKeyConstraint(
            ["workspace_id", "document_id", "pre_agent_version_id"],
            [
                "platform.document_versions.workspace_id",
                "platform.document_versions.document_id",
                "platform.document_versions.id",
            ],
            ondelete="SET NULL (pre_agent_version_id)",
        ),
        CheckConstraint("initial_revision >= 0", name="initial_revision_non_negative"),
        # One active run per document and editor session (§IX-B).
        Index(
            "uq_runs_document_id_editor_session_id_active",
            "document_id",
            "editor_session_id",
            unique=True,
            postgresql_where="status IN ('pending', 'running')",
        ),
        Index(None, "account_id", "workspace_id", "conversation_id"),
        Index(None, "workspace_id", "document_id", "pre_agent_version_id"),
        # Expiry job: find active runs whose lease ran out.
        Index(None, "status", "lease_until"),
        {"schema": DbSchema.AGENT},
    )

    conversation_id: Mapped[uuid.UUID]
    account_id: Mapped[uuid.UUID]
    workspace_id: Mapped[uuid.UUID]
    document_id: Mapped[uuid.UUID]
    # An editor tab, not a row of auth.sessions.
    editor_session_id: Mapped[uuid.UUID]
    initial_revision: Mapped[int] = mapped_column(BigInteger)
    pre_agent_version_id: Mapped[uuid.UUID | None]
    recorded_pre_agent_version_id: Mapped[uuid.UUID | None]
    mode: Mapped[AgentMode] = mapped_column(text_enum(AgentMode, "mode"))
    variant: Mapped[str]
    model: Mapped[str]
    prompt_version: Mapped[str]
    catalog_fingerprint: Mapped[str]
    status: Mapped[RunStatus] = mapped_column(text_enum(RunStatus, "status"))
    lease_until: Mapped[datetime | None]
    finished_at: Mapped[datetime | None]
