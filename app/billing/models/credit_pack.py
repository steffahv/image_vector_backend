from sqlalchemy import BigInteger, CheckConstraint, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema, UUIDPrimaryKey


class CreditPack(UUIDPrimaryKey, CreatedAt, Base):
    __tablename__ = "credit_packs"
    __table_args__ = (
        UniqueConstraint("gateway", "gateway_product_id"),
        CheckConstraint("credits > 0", name="credits_positive"),
        CheckConstraint("price_cents >= 0", name="price_cents_non_negative"),
        {"schema": DbSchema.BILLING},
    )

    credits: Mapped[int] = mapped_column(BigInteger)
    price_cents: Mapped[int] = mapped_column(BigInteger)
    currency: Mapped[str]
    gateway: Mapped[str]
    gateway_product_id: Mapped[str]
    active: Mapped[bool]
