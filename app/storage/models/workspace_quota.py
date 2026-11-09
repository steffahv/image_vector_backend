import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, func
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema


class WorkspaceQuota(Base):
    """Storage space of a workspace: its limit, what is used and what is reserved by uploads.

    There is no CHECK `used_bytes <= limit_bytes` on purpose: after a plan downgrade a
    workspace can be over its limit, and that must not block reading or deleting (§IX-B).
    New uploads are refused by the service instead.
    """

    __tablename__ = "workspace_quotas"
    __table_args__ = (
        CheckConstraint("limit_bytes >= 0", name="limit_bytes_non_negative"),
        CheckConstraint("used_bytes >= 0", name="used_bytes_non_negative"),
        CheckConstraint("reserved_bytes >= 0", name="reserved_bytes_non_negative"),
        {"schema": DbSchema.STORAGE},
    )

    workspace_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform.workspaces.id"), primary_key=True
    )
    limit_bytes: Mapped[int] = mapped_column(BigInteger)
    used_bytes: Mapped[int] = mapped_column(BigInteger)
    reserved_bytes: Mapped[int] = mapped_column(BigInteger)
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
