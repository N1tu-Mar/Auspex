import uuid
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import DateTime, Engine, Text, create_engine, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column

from app.settings import get_settings


class Base(DeclarativeBase):
    pass


class BetSlipRecord(Base):
    """Append-only snapshot of a submitted slip. Corrections insert a new row."""

    __tablename__ = "bet_slips"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    original_input: Mapped[str | None] = mapped_column(Text)
    slip: Mapped[dict[str, Any]] = mapped_column(JSONB)


@lru_cache
def get_engine() -> Engine:
    return create_engine(
        str(get_settings().database_url),
        pool_pre_ping=True,
        # Every session runs in UTC; render local time only in the UI.
        connect_args={"connect_timeout": 3, "options": "-c timezone=UTC"},
    )


def get_session() -> Iterator[Session]:
    with Session(get_engine()) as session:
        yield session
