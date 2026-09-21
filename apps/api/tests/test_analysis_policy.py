"""Estimate -> EV -> recommendation wiring, with a stubbed estimator (no model is ACTIVE yet)."""

import asyncio
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest

from app import analysis
from app.analysis import analyze, collect
from app.analysis_record import AnalysisRecord, AnalysisRequest
from app.providers import Estimation
from auspex_contracts import BetSlip
from auspex_prediction.registry import InMemoryModelRegistry
from auspex_prediction.uncertainty import ConfidenceTier
from auspex_research.fixtures import FixtureTransport, json_fixture
from auspex_research.polymarket import PolymarketUSClient
from auspex_research.transport import Fetcher, RetryPolicy
from auspex_sports.adapter import LegEstimate

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
MARKET_URL = "https://gateway.polymarket.us/v1/market/id/fixture-mkt-1001"
SLIP = BetSlip.model_validate(
    {
        "stake_usd": "10.00",
        "legs": [
            {
                "sport": "NFL",
                "league": "NFL",
                "event_id": "9001",
                "event_start_utc": "2026-09-27T20:25:00Z",
                "home_participant": "Buffalo Bills",
                "away_participant": "Kansas City Chiefs",
                "market_type": "MONEYLINE",
                "side": "AWAY",
                "polymarket_market_id": "fixture-mkt-1001",
                "market_price_usd": "0.54",
                "settlement_rule_ref": "r",
            }
        ],
    }
)


def estimate(p: str, low: str, high: str) -> LegEstimate:
    return LegEstimate(
        model_probability=Decimal(p),
        probability_low=Decimal(low),
        probability_high=Decimal(high),
        model_id="m",
        model_version="m-1",
        code_version="c",
        evaluation_artifact_id="a",
        snapshot_captured_at_utc=NOW,
        as_of_utc=NOW,
        evidence_confidence=ConfidenceTier.HIGH,
        prediction_confidence=ConfidenceTier.HIGH,
    )


def run(monkeypatch: pytest.MonkeyPatch, est: LegEstimate, **request: Any) -> AnalysisRecord:
    monkeypatch.setattr(analysis, "estimate_leg", lambda *_: est)
    fixture = json_fixture("polymarket_us/market_by_slug.nfl_moneyline.synthetic.json")
    fetcher = Fetcher(
        FixtureTransport({MARKET_URL: fixture}), RetryPolicy(max_attempts=1), clock=lambda: NOW
    )
    collected = asyncio.run(collect(SLIP.legs, PolymarketUSClient(fetcher), [], lambda: NOW))
    return analyze(
        SLIP,
        AnalysisRequest(intake_trace_id=uuid.uuid4(), **request),
        collected,
        Estimation(InMemoryModelRegistry(), {}),
        as_of=NOW,
        created_at=NOW,
        code_version="test-sha",
        bet_slip_id=uuid.uuid4(),
        intake_record_id=uuid.uuid4(),
    )


FEES = {"estimated_fees_usd": "0.10", "estimated_slippage_usd": "0.05"}


def test_clear_edge_is_consider_with_expected_value(monkeypatch: pytest.MonkeyPatch) -> None:
    run_ = run(monkeypatch, estimate("0.65", "0.60", "0.70"), **FEES).analysis
    assert run_.recommendation.recommendation == "CONSIDER"
    assert run_.model_version == "m-1"
    assert run_.expected_value is not None
    assert run_.expected_value.costs.gross_payout_usd == Decimal("18.51")
    assert run_.legs[0].edge_probability_points == Decimal("11.00")


def test_price_far_above_model_is_avoid(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = run(monkeypatch, estimate("0.40", "0.35", "0.45"), **FEES).analysis.recommendation
    assert rec.recommendation == "AVOID"


def test_thin_conservative_edge_is_pass(monkeypatch: pytest.MonkeyPatch) -> None:
    rec = run(monkeypatch, estimate("0.60", "0.50", "0.70"), **FEES).analysis.recommendation
    assert rec.recommendation == "PASS"


def test_unsupplied_fees_mean_insufficient_data_not_assumed_zero(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis_ = run(monkeypatch, estimate("0.65", "0.60", "0.70")).analysis
    rec = analysis_.recommendation
    assert rec.recommendation == "INSUFFICIENT_DATA"
    assert rec.insufficient_data is not None
    assert "fees and slippage" in rec.insufficient_data.reasons[0]
    assert analysis_.expected_value is None
