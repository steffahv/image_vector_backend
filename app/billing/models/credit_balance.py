import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, func, text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, DbSchema


class CreditBalance(Base):
    __tablename__ = "credit_balances"
    __table_args__ = (
        CheckConstraint("reserved >= 0 AND reserved <= balance", name="within_balance"),
        {"schema": DbSchema.BILLING},
    )

    account_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("platform.accounts.id"), primary_key=True
    )
    balance: Mapped[int] = mapped_column(BigInteger)
    reserved: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
