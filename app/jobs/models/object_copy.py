import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema, sha256_check


class ObjectCopy(Base):
    """Evidence that a file was copied to a backup destination and checked there."""

    __tablename__ = "object_copies"
    __table_args__ = (
        CheckConstraint(sha256_check("sha256"), name="sha256_length"),
        CheckConstraint("size_bytes >= 0", name="size_bytes_non_negative"),
        {"schema": DbSchema.OPERATIONS},
    )

    object_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("storage.objects.id"), primary_key=True)
    destination: Mapped[str] = mapped_column(primary_key=True)
    key: Mapped[str]
    sha256: Mapped[bytes]
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    verified_at: Mapped[datetime]
