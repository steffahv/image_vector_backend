import uuid
from datetime import datetime

from sqlalchemy import DateTime, Text, Uuid
from sqlalchemy.orm import Mapped

from app.core.model_base import Base, DbSchema, Timestamps, UUIDPrimaryKey


class _Example(UUIDPrimaryKey, Timestamps, Base):
    __tablename__ = "examples"
    __table_args__ = {"schema": DbSchema.PLATFORM}

    other_id: Mapped[uuid.UUID]
    label: Mapped[str]
    seen_at: Mapped[datetime]


def test_shared_columns_use_uuid_text_and_timestamptz() -> None:
    table = _Example.__table__
    try:
        assert table.schema == "platform"
        assert table.c.id.primary_key
        assert isinstance(table.c.id.type, Uuid)
        assert isinstance(table.c.other_id.type, Uuid)
        assert isinstance(table.c.label.type, Text)
        for column in ("created_at", "updated_at", "seen_at"):
            column_type = table.c[column].type
            assert isinstance(column_type, DateTime) and column_type.timezone
    finally:
        Base.metadata.remove(table)
