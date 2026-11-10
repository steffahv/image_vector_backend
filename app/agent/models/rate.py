from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Index
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey


class Rate(UUIDPrimaryKey, CreatedAt, Base):
    """Price of a provider's model from a date on. Global: no account data.

    A new price is a new row; old rows stay, because they explain the cost of past usage.
    Prices are integers in micro-units of `currency` per `token_basis` tokens.
    """

    __tablename__ = "rates"
    __table_args__ = (
        CheckConstraint("input_price_micro >= 0", name="input_price_micro_non_negative"),
        CheckConstraint("output_price_micro >= 0", name="output_price_micro_non_negative"),
        CheckConstraint("token_basis > 0", name="token_basis_positive"),
        # Finding the price in force for a model at a given time.
        Index(None, "provider", "model", "effective_from"),
        {"schema": DbSchema.AGENT},
    )

    provider: Mapped[str]
    model: Mapped[str]
    input_price_micro: Mapped[int] = mapped_column(BigInteger)
    output_price_micro: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str]
    token_basis: Mapped[int] = mapped_column(BigInteger)
    effective_from: Mapped[datetime]
