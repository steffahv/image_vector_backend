from sqlalchemy.orm import Mapped, mapped_column

from app.core.model_base import Base, CreatedAt, DbSchema


class Plan(CreatedAt, Base):
    __tablename__ = "plans"
    __table_args__ = {"schema": DbSchema.BILLING}

    id: Mapped[str] = mapped_column(primary_key=True)
    name: Mapped[str]
    active: Mapped[bool]
