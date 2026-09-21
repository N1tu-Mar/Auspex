"""Requires PostgreSQL (`docker compose up -d db`). Run with `pnpm test:db`."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import BetSlipRecord, IntakeRecord, get_engine

pytestmark = pytest.mark.db

ALEMBIC_INI = str(Path(__file__).parents[3] / "alembic.ini")


def test_migrations_apply_and_match_models() -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    command.check(config)  # raises if models drift from migrations


def test_migrations_downgrade_and_reapply() -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    command.downgrade(config, "0001")
    command.upgrade(config, "head")


def test_bet_slip_snapshot_round_trip_in_utc() -> None:
    with Session(get_engine()) as session:
        record = BetSlipRecord(original_input="raw", slip={"legs": []})
        session.add(record)
        session.flush()
        session.refresh(record)
        assert record.created_at.utcoffset() == timedelta(0)
        assert record.slip == {"legs": []}
        session.rollback()


def intake(state: str, **overrides: object) -> IntakeRecord:
    fields: dict[str, object] = {
        "id": uuid.uuid4(),
        "received_at": datetime.now(UTC),
        "source": "paste",
        "state": state,
        "result": {"state": state},
    }
    return IntakeRecord(**(fields | overrides))


def test_intake_record_links_slip_and_supersedes_chain() -> None:
    with Session(get_engine()) as session:
        slip = BetSlipRecord(original_input="raw", slip={"legs": []})
        first = intake("NEEDS_RESOLUTION", original_input="raw")
        session.add_all([slip, first])
        session.flush()
        second = intake("RESOLVED", bet_slip_id=slip.id, supersedes_id=first.id)
        session.add(second)
        session.flush()
        session.refresh(second)
        assert second.received_at.utcoffset() == timedelta(0)
        assert (second.bet_slip_id, second.supersedes_id) == (slip.id, first.id)
        session.rollback()


@pytest.mark.parametrize(
    "record",
    [
        pytest.param(lambda: intake("PENDING"), id="unknown-state"),
        pytest.param(lambda: intake("RESOLVED", source="email"), id="unknown-source"),
        pytest.param(lambda: intake("REJECTED", bet_slip_id=uuid.uuid4()), id="slip-not-resolved"),
        pytest.param(lambda: intake("RESOLVED", bet_slip_id=uuid.uuid4()), id="missing-slip"),
    ],
)
def test_intake_record_constraints_reject_invalid_rows(record: Callable[[], IntakeRecord]) -> None:
    with Session(get_engine()) as session:
        session.add(record())
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()
