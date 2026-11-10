import uuid

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Index, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey


class CreditMovement(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "credit_movements"
    __table_args__ = (
        UniqueConstraint("account_id", "reason", "reference"),
        CheckConstraint("amount <> 0", name="amount_non_zero"),
        Index(None, "account_id", "created_at"),
        {"schema": DbSchema.BILLING},
    )

    account_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("platform.accounts.id"))
    amount: Mapped[int] = mapped_column(BigInteger)
    reason: Mapped[str]
    reference: Mapped[str]
