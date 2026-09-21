"""Requires PostgreSQL (`docker compose up -d db`). Run with `pnpm test:db`."""

import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import delete, text, update
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from app.analysis_models import (
    AnalysisLegRecord,
    AnalysisRunRecord,
    EventRecord,
    EventSnapshotRecord,
    EvidenceItemRecord,
    EvidenceSnapshotItemRecord,
    EvidenceSnapshotRecord,
    FeatureSnapshotRecord,
    MarketRecord,
    MarketSnapshotRecord,
    ProviderFailureRecord,
    SourceRecord,
)
from app.db import Base, BetSlipRecord, IntakeRecord, get_engine

pytestmark = pytest.mark.db

ALEMBIC_INI = str(Path(__file__).parents[2] / "alembic.ini")
NOW = datetime(2026, 10, 4, 18, tzinfo=UTC)
SHA_A, SHA_B = "a" * 64, "b" * 64
GUARDED = ["bet_slips", "intake_records"] + [
    t for t in sorted(Base.metadata.tables) if t not in {"bet_slips", "intake_records"}
]


def test_downgrade_through_each_new_revision_and_reapply() -> None:
    config = Config(ALEMBIC_INI)
    command.upgrade(config, "head")
    for revision in ("0005", "0004", "0003", "0002"):
        command.downgrade(config, revision)
    command.upgrade(config, "head")
    command.check(config)


def seed(session: Session) -> dict[str, Any]:
    """Insert one complete, valid chain from source to analysis. Caller rolls back."""
    source = SourceRecord(
        provider="polymarket_us",
        publisher="Polymarket US",
        url="https://example.com/m",
        retrieved_at=NOW,
    )
    event = EventRecord(event_id="evt-1", sport="NFL", league="NFL", created_at=NOW)
    session.add_all([source, event])
    session.flush()
    event_snapshot = EventSnapshotRecord(
        event_id="evt-1",
        captured_at=NOW,
        event_start_utc=NOW + timedelta(days=1),
        status="PREGAME",
        source_id=source.id,
    )
    market = MarketRecord(
        provider="polymarket_us",
        market_id="m-1",
        event_id="evt-1",
        market_type="MONEYLINE",
        created_at=NOW,
    )
    session.add_all([event_snapshot, market])
    session.flush()
    market_snapshot = MarketSnapshotRecord(
        provider="polymarket_us",
        market_id="m-1",
        captured_at=NOW,
        is_open=True,
        best_bid_usd=Decimal("0.4"),
        best_ask_usd=Decimal("0.45"),
        sides=[],
        warnings=[],
        source_id=source.id,
    )
    item = EvidenceItemRecord(
        id=SHA_A,
        event_id="evt-1",
        category="INJURY",
        claim_kind="CONFIRMED_FACT",
        extracted_fact="QB out",
        source_id=source.id,
        derived_from=[],
    )
    snapshot = EvidenceSnapshotRecord(id=SHA_B, event_id="evt-1", created_at=NOW)
    slip = BetSlipRecord(original_input="raw", slip={"legs": []})
    session.add_all([market_snapshot, item, snapshot, slip])
    session.flush()
    session.add_all(
        [
            EvidenceSnapshotItemRecord(snapshot_id=SHA_B, position=0, evidence_id=SHA_A),
            ProviderFailureRecord(
                snapshot_id=SHA_B, provider="espn", kind="TIMEOUT", message="t", occurred_at=NOW
            ),
        ]
    )
    features = FeatureSnapshotRecord(
        event_id="evt-1",
        sport="NFL",
        captured_at=NOW,
        feature_set_version="v1",
        evidence_snapshot_id=SHA_B,
        features={"qb": {"value_text": "OUT"}},
    )
    session.add(features)
    session.flush()
    return {
        "source": source,
        "event_snapshot": event_snapshot,
        "market_snapshot": market_snapshot,
        "snapshot": snapshot,
        "features": features,
        "slip": slip,
    }


def run_row(slip_id: uuid.UUID, **overrides: object) -> AnalysisRunRecord:
    fields: dict[str, object] = {
        "created_at": NOW,
        "as_of_utc": NOW,
        "bet_slip_id": slip_id,
        "code_version": "abc123",
        "model_version": "m1",
        "recommendation": "PASS",
        "recommendation_reason": "No edge.",
    }
    return AnalysisRunRecord(**(fields | overrides))


def leg_row(analysis_id: uuid.UUID, **overrides: object) -> AnalysisLegRecord:
    fields: dict[str, object] = {
        "analysis_id": analysis_id,
        "leg_index": 0,
        "market_implied_probability": Decimal("0.5"),
        "model_probability": Decimal("0.55"),
        "probability_low": Decimal("0.5"),
        "probability_high": Decimal("0.6"),
        "estimate_model_version": "m1",
        "estimate_snapshot_captured_at": NOW,
        "edge_probability_points": Decimal("5"),
    }
    return AnalysisLegRecord(**(fields | overrides))


def test_full_analysis_chain_round_trips_exactly_in_utc() -> None:
    with Session(get_engine()) as session:
        rows = seed(session)
        run = run_row(rows["slip"].id, expected_value={"expected_profit_usd": "2.00"})
        session.add(run)
        session.flush()
        exact = Decimal("0.123456789012345678")
        session.add(
            leg_row(
                run.id,
                market_implied_probability=exact,
                event_snapshot_id=rows["event_snapshot"].id,
                market_snapshot_id=rows["market_snapshot"].id,
                evidence_snapshot_id=SHA_B,
                feature_snapshot_id=rows["features"].id,
            )
        )
        session.flush()
        session.expire_all()
        leg = session.get(AnalysisLegRecord, (run.id, 0))
        assert leg is not None
        assert leg.market_implied_probability == exact
        assert session.get(AnalysisRunRecord, run.id).created_at.utcoffset() == timedelta(0)  # type: ignore[union-attr]
        session.rollback()


@pytest.mark.parametrize("table", GUARDED)
def test_every_table_rejects_truncate(table: str) -> None:
    with Session(get_engine()) as session:
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(text(f"TRUNCATE {table} CASCADE"))
        session.rollback()


def test_rows_cannot_be_updated_or_deleted() -> None:
    attempts: list[Callable[[Any], object]] = [
        lambda r: update(BetSlipRecord).values(original_input="edited"),
        lambda r: update(EvidenceItemRecord).values(extracted_fact="edited"),
        lambda r: delete(EvidenceItemRecord),
        lambda r: update(EvidenceSnapshotItemRecord).values(position=9),
        lambda r: update(AnalysisRunRecord).values(recommendation="AVOID"),
        lambda r: delete(AnalysisRunRecord),
        lambda r: update(AnalysisLegRecord).values(leg_index=3),
        lambda r: update(MarketSnapshotRecord).values(is_open=False),
        lambda r: delete(FeatureSnapshotRecord),
    ]
    for attempt in attempts:
        with Session(get_engine()) as session:
            rows = seed(session)
            run = run_row(rows["slip"].id)
            session.add(run)
            session.flush()
            session.add(leg_row(run.id))
            session.flush()
            with pytest.raises(DBAPIError, match="append-only"):
                session.execute(attempt(rows))  # type: ignore[call-overload]
            session.rollback()


def test_intake_records_are_append_only_too() -> None:
    with Session(get_engine()) as session:
        record = IntakeRecord(
            id=uuid.uuid4(), received_at=NOW, source="paste", state="REJECTED", result={}
        )
        session.add(record)
        session.flush()
        with pytest.raises(DBAPIError, match="append-only"):
            session.execute(update(IntakeRecord).values(state="RESOLVED"))
        session.rollback()


BAD_ROWS: dict[str, Callable[[dict[str, Any]], list[object]]] = {
    "event-sport": lambda r: [
        EventRecord(event_id="x", sport="CRICKET", league="l", created_at=NOW)
    ],
    "event-snapshot-status": lambda r: [
        EventSnapshotRecord(
            event_id="evt-1",
            captured_at=NOW,
            event_start_utc=NOW,
            status="SOON",
            source_id=r["source"].id,
        )
    ],
    "market-type": lambda r: [
        MarketRecord(
            provider="p", market_id="x", event_id="evt-1", market_type="PARLAY", created_at=NOW
        )
    ],
    "market-unknown-event": lambda r: [
        MarketRecord(provider="p", market_id="x", event_id="nope", created_at=NOW)
    ],
    "market-snapshot-unknown-market": lambda r: [
        MarketSnapshotRecord(
            provider="p",
            market_id="nope",
            captured_at=NOW,
            is_open=True,
            sides=[],
            warnings=[],
            source_id=r["source"].id,
        )
    ],
    "market-bid-above-ask": lambda r: [
        MarketSnapshotRecord(
            provider="polymarket_us",
            market_id="m-1",
            captured_at=NOW,
            is_open=True,
            sides=[],
            warnings=[],
            best_bid_usd=Decimal("0.6"),
            best_ask_usd=Decimal("0.5"),
            source_id=r["source"].id,
        )
    ],
    "market-price-out-of-range": lambda r: [
        MarketSnapshotRecord(
            provider="polymarket_us",
            market_id="m-1",
            captured_at=NOW,
            is_open=True,
            sides=[],
            warnings=[],
            best_ask_usd=Decimal("1"),
            source_id=r["source"].id,
        )
    ],
    "evidence-id-not-sha": lambda r: [
        EvidenceItemRecord(
            id="short",
            event_id="evt-1",
            category="NEWS",
            claim_kind="RUMOR",
            extracted_fact="f",
            source_id=r["source"].id,
            derived_from=[],
        )
    ],
    "evidence-inference-without-citation": lambda r: [
        EvidenceItemRecord(
            id="c" * 64,
            event_id="evt-1",
            category="NEWS",
            claim_kind="INFERENCE",
            extracted_fact="f",
            source_id=r["source"].id,
            derived_from=[],
        )
    ],
    "evidence-fact-with-citation": lambda r: [
        EvidenceItemRecord(
            id="d" * 64,
            event_id="evt-1",
            category="NEWS",
            claim_kind="RUMOR",
            extracted_fact="f",
            source_id=r["source"].id,
            derived_from=[SHA_A],
        )
    ],
    "snapshot-duplicate-position": lambda r: [
        EvidenceSnapshotItemRecord(snapshot_id=SHA_B, position=0, evidence_id=SHA_A)
    ],
    "failure-kind": lambda r: [
        ProviderFailureRecord(provider="p", kind="EXPLODED", message="m", occurred_at=NOW)
    ],
    "feature-sport": lambda r: [
        FeatureSnapshotRecord(
            event_id="evt-1", sport="NHL", captured_at=NOW, feature_set_version="v", features={}
        )
    ],
    "run-unknown-slip": lambda r: [run_row(uuid.uuid4())],
    "run-unknown-recommendation": lambda r: [run_row(r["slip"].id, recommendation="BUY")],
    "run-insufficient-without-reasons": lambda r: [
        run_row(r["slip"].id, recommendation="INSUFFICIENT_DATA")
    ],
    "run-reasons-without-insufficient": lambda r: [
        run_row(r["slip"].id, insufficient_reasons=["why"])
    ],
    "run-empty-reasons": lambda r: [
        run_row(r["slip"].id, recommendation="INSUFFICIENT_DATA", insufficient_reasons=[])
    ],
    "run-as-of-after-created": lambda r: [
        run_row(r["slip"].id, as_of_utc=NOW + timedelta(seconds=1))
    ],
}


@pytest.mark.parametrize("name", BAD_ROWS)
def test_schema_rejects_invalid_row(name: str) -> None:
    with Session(get_engine()) as session:
        rows = seed(session)
        session.add_all(BAD_ROWS[name](rows))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


BAD_LEGS: dict[str, dict[str, object]] = {
    "probability-above-one": {"market_implied_probability": Decimal("1.1")},
    "interval-inverted": {"probability_low": Decimal("0.7")},
    "estimate-outside-interval": {"model_probability": Decimal("0.9")},
    "estimate-without-edge": {"edge_probability_points": None},
    "estimate-and-reasons": {"insufficient_reasons": ["x"]},
    "neither-estimate-nor-reasons": {
        "model_probability": None,
        "probability_low": None,
        "probability_high": None,
        "estimate_model_version": None,
        "estimate_snapshot_captured_at": None,
        "edge_probability_points": None,
    },
    "empty-reasons": {
        "model_probability": None,
        "probability_low": None,
        "probability_high": None,
        "estimate_model_version": None,
        "estimate_snapshot_captured_at": None,
        "edge_probability_points": None,
        "insufficient_reasons": [],
    },
    "negative-index": {"leg_index": -1},
    "unknown-snapshot": {"market_snapshot_id": uuid.uuid4()},
}


@pytest.mark.parametrize("name", BAD_LEGS)
def test_schema_rejects_invalid_leg(name: str) -> None:
    with Session(get_engine()) as session:
        rows = seed(session)
        run = run_row(rows["slip"].id)
        session.add(run)
        session.flush()
        session.add(leg_row(run.id, **BAD_LEGS[name]))
        with pytest.raises(IntegrityError):
            session.flush()
        session.rollback()


def test_insufficient_data_leg_and_run_are_accepted() -> None:
    with Session(get_engine()) as session:
        rows = seed(session)
        run = run_row(
            rows["slip"].id, recommendation="INSUFFICIENT_DATA", insufficient_reasons=["stale"]
        )
        session.add(run)
        session.flush()
        session.add(
            leg_row(
                run.id,
                model_probability=None,
                probability_low=None,
                probability_high=None,
                estimate_model_version=None,
                estimate_snapshot_captured_at=None,
                edge_probability_points=None,
                insufficient_reasons=["no lineup"],
            )
        )
        session.flush()
        session.rollback()
