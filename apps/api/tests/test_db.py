"""Requires PostgreSQL (`docker compose up -d db`). Run with `pnpm test:db`."""

from datetime import timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.orm import Session

from app.db import BetSlipRecord, get_engine

pytestmark = pytest.mark.db

ALEMBIC_INI = str(Path(__file__).parents[3] / "alembic.ini")


def test_migrations_apply_and_match_models() -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    command.check(config)  # raises if models drift from migrations


def test_bet_slip_snapshot_round_trip_in_utc() -> None:
    with Session(get_engine()) as session:
        record = BetSlipRecord(original_input="raw", slip={"legs": []})
        session.add(record)
        session.flush()
        session.refresh(record)
        assert record.created_at.utcoffset() == timedelta(0)
        assert record.slip == {"legs": []}
        session.rollback()
