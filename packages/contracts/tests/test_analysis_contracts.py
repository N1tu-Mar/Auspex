import json
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from pydantic import ValidationError

from auspex_contracts import (
    AnalysisRun,
    ClaimKind,
    EvidenceCategory,
    EvidenceItem,
    EvidenceSnapshot,
    FeatureSnapshot,
    LegEstimate,
    MarketSnapshot,
    ProviderErrorKind,
    Recommendation,
)

NOW = "2026-10-04T18:00:00Z"
SHA = "a" * 64
SOURCE = {
    "provider": "espn",
    "publisher": "ESPN",
    "url": "https://example.com/a",
    "published_at": "2026-10-04T15:00:00Z",
    "retrieved_at": "2026-10-04T16:00:00Z",
}


def estimate(p: str = "0.55") -> dict[str, Any]:
    return {
        "model_probability": p,
        "interval": {"low": "0.50", "high": "0.60"},
        "model_version": "nfl-0.1",
        "snapshot_captured_at_utc": NOW,
    }


def leg(index: int) -> dict[str, Any]:
    return {
        "leg_index": index,
        "market_implied_probability": "0.5",
        "estimate": estimate(),
        "edge_probability_points": "5.0",
    }


def run(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "created_at": "2026-10-04T18:05:00Z",
        "as_of_utc": NOW,
        "bet_slip_id": str(uuid4()),
        "code_version": "267557e",
        "model_version": "nfl-0.1",
        "legs": [leg(0), leg(1)],
        "combo": {
            "naive_baseline": {"probability": "0.3025"},
            "warnings": [
                {"kind": "SHARED_GAME", "leg_indices": [0, 1], "explanation": "same game"}
            ],
            "joint_probability": {"reasons": ["no validated correlation model"]},
        },
        "expected_value": {
            "costs": {
                "stake_usd": "10.00",
                "gross_payout_usd": "40.00",
                "estimated_fees_usd": "0.10",
                "estimated_slippage_usd": "0",
            },
            "model_probability": "0.3025",
            "break_even_probability": "0.2525",
            "edge_probability_points": "5.00",
            "expected_profit_usd": "2.00",
            "expected_return_pct": "20.0",
        },
        "recommendation": {"recommendation": "CONSIDER", "reason": "Positive edge."},
    }
    return base | overrides


def test_analysis_run_round_trips_with_decimal_strings() -> None:
    parsed = AnalysisRun.model_validate(run())
    dumped = json.loads(parsed.model_dump_json())
    assert dumped["legs"][0]["estimate"]["model_probability"] == "0.55"
    assert dumped["combo"]["naive_baseline"]["probability"] == "0.3025"
    assert dumped["as_of_utc"] == NOW
    assert AnalysisRun.model_validate_json(parsed.model_dump_json()) == parsed


def test_insufficient_data_run_carries_reasons() -> None:
    insufficient = {"reasons": ["injury report stale"]}
    legs = [
        {
            "leg_index": 0,
            "market_implied_probability": "0.5",
            "insufficient_data": insufficient,
        }
    ]
    parsed = AnalysisRun.model_validate(
        run(
            legs=legs,
            combo=None,
            expected_value=None,
            recommendation={
                "recommendation": "INSUFFICIENT_DATA",
                "reason": "Evidence is stale.",
                "insufficient_data": insufficient,
            },
        )
    )
    assert parsed.recommendation.recommendation is Recommendation.INSUFFICIENT_DATA
    assert parsed.legs[0].insufficient_data is not None
    assert parsed.legs[0].insufficient_data.status is Recommendation.INSUFFICIENT_DATA


def broken(mutate: Any) -> dict[str, Any]:
    data = deepcopy(run())
    mutate(data)
    return data


@pytest.mark.parametrize(
    "data",
    [
        pytest.param(
            broken(lambda d: d["legs"][0].update(estimate=estimate("0.7"))), id="p-outside"
        ),
        pytest.param(
            broken(lambda d: d["legs"][0]["estimate"]["interval"].update(low="0.9")), id="low>high"
        ),
        pytest.param(
            broken(lambda d: d["legs"][0]["estimate"].update(model_probability="1.5")), id="p>1"
        ),
        pytest.param(broken(lambda d: d["legs"][0].pop("estimate")), id="no-estimate-no-reasons"),
        pytest.param(
            broken(lambda d: d["legs"][0].update(insufficient_data={"reasons": ["x"]})),
            id="both-estimate-and-reasons",
        ),
        pytest.param(broken(lambda d: d["legs"][0].pop("edge_probability_points")), id="no-edge"),
        pytest.param(broken(lambda d: d["legs"][1].update(leg_index=5)), id="leg-index-gap"),
        pytest.param(broken(lambda d: d.update(combo=None)), id="two-legs-no-combo"),
        pytest.param(broken(lambda d: d.update(legs=d["legs"][:1])), id="one-leg-with-combo"),
        pytest.param(
            broken(lambda d: d.update(as_of_utc="2026-10-04T19:00:00Z")), id="as-of-future"
        ),
        pytest.param(broken(lambda d: d.update(expected_value=None)), id="consider-without-ev"),
        pytest.param(broken(lambda d: d.update(code_version="")), id="no-code-version"),
        pytest.param(broken(lambda d: d.update(as_of_utc="2026-10-04T18:00:00")), id="naive-time"),
        pytest.param(broken(lambda d: d.update(surprise=1)), id="unknown-field"),
        pytest.param(
            broken(lambda d: d["recommendation"].update(recommendation="INSUFFICIENT_DATA")),
            id="insufficient-without-reasons",
        ),
        pytest.param(
            broken(lambda d: d["recommendation"].update(insufficient_data={"reasons": ["x"]})),
            id="reasons-without-insufficient",
        ),
        pytest.param(
            broken(lambda d: d["combo"]["warnings"][0].update(magnitude="0.4")), id="magnitude"
        ),
        pytest.param(
            broken(lambda d: d["combo"]["joint_probability"].update(reasons=[])), id="empty-reasons"
        ),
    ],
)
def test_analysis_run_rejects_invalid(data: dict[str, Any]) -> None:
    with pytest.raises(ValidationError):
        AnalysisRun.model_validate(data)


def test_leg_estimate_timestamp_normalizes_to_utc() -> None:
    e = LegEstimate.model_validate(
        estimate() | {"snapshot_captured_at_utc": "2026-10-04T14:00:00-04:00"}
    )
    assert e.snapshot_captured_at_utc == datetime(2026, 10, 4, 18, tzinfo=UTC)


def item(**overrides: Any) -> dict[str, Any]:
    base = {
        "event_id": "evt-1",
        "category": "INJURY",
        "claim_kind": "CONFIRMED_FACT",
        "extracted_fact": "QB is out.",
        "source": SOURCE,
    }
    return base | overrides


def test_evidence_ids_are_content_hashes_and_tamper_evident() -> None:
    a = EvidenceItem.model_validate(item())
    assert len(a.evidence_id) == 64
    assert EvidenceItem.model_validate(item()).evidence_id == a.evidence_id
    assert (
        EvidenceItem.model_validate(item(extracted_fact="QB is in.")).evidence_id != a.evidence_id
    )
    with pytest.raises(ValidationError, match="does not match content"):
        EvidenceItem.model_validate(item(evidence_id=SHA))
    assert EvidenceItem.model_validate(a.model_dump(mode="json")) == a


def test_inference_must_cite_evidence_in_the_snapshot() -> None:
    fact = EvidenceItem.model_validate(item())
    with pytest.raises(ValidationError, match="must cite"):
        EvidenceItem.model_validate(item(claim_kind="INFERENCE"))
    inferred = item(claim_kind="INFERENCE", derived_from=[fact.evidence_id])
    snap = EvidenceSnapshot.model_validate(
        {"event_id": "evt-1", "created_at": NOW, "items": [fact.model_dump(mode="json"), inferred]}
    )
    assert len(snap.snapshot_id) == 64
    assert snap.items[1].claim_kind is ClaimKind.INFERENCE
    with pytest.raises(ValidationError, match="not in snapshot"):
        EvidenceSnapshot.model_validate(
            {"event_id": "evt-1", "created_at": NOW, "items": [inferred]}
        )


def test_evidence_snapshot_rejects_wrong_event_and_late_retrieval() -> None:
    with pytest.raises(ValidationError, match="belongs to event"):
        EvidenceSnapshot.model_validate({"event_id": "evt-2", "created_at": NOW, "items": [item()]})
    with pytest.raises(ValidationError, match="after snapshot creation"):
        EvidenceSnapshot.model_validate(
            {"event_id": "evt-1", "created_at": "2026-10-04T10:00:00Z", "items": [item()]}
        )


def test_evidence_snapshot_keeps_provider_failures() -> None:
    failure = {
        "provider": "espn",
        "kind": "TIMEOUT",
        "message": "timed out",
        "occurred_at": NOW,
    }
    snap = EvidenceSnapshot.model_validate(
        {"event_id": "evt-1", "created_at": NOW, "items": [], "failures": [failure]}
    )
    assert snap.failures[0].kind is ProviderErrorKind.TIMEOUT
    assert EvidenceItem.model_validate(item()).category is EvidenceCategory.INJURY


def test_market_snapshot_validates_prices() -> None:
    base = {
        "provider": "polymarket_us",
        "market_id": "m-1",
        "captured_at": NOW,
        "is_open": True,
        "best_bid_usd": "0.4",
        "best_ask_usd": "0.45",
        "source": SOURCE,
    }
    assert MarketSnapshot.model_validate(base).best_ask_usd == Decimal("0.45")
    for bad in ({"best_bid_usd": "0.5"}, {"best_ask_usd": "1"}, {"fee_coefficient": "-1"}):
        with pytest.raises(ValidationError):
            MarketSnapshot.model_validate(base | bad)


def test_feature_snapshot_values_and_timing() -> None:
    obs = {"observed_at": "2026-10-04T17:00:00Z", "source_ref": "src-1"}
    base: dict[str, Any] = {
        "event_id": "evt-1",
        "sport": "NFL",
        "captured_at": NOW,
        "feature_set_version": "nfl-features-1",
        "features": {
            "qb_status": obs | {"value_text": "OUT"},
            "team_epa": obs | {"value_decimal": "0.113"},
            "rest_days": obs,  # unknown
        },
    }
    snap = FeatureSnapshot.model_validate(base)
    assert snap.features["team_epa"].value_decimal == Decimal("0.113")
    assert json.loads(snap.model_dump_json())["features"]["team_epa"]["value_decimal"] == "0.113"
    both = deepcopy(base)
    both["features"]["team_epa"]["value_text"] = "x"
    late = deepcopy(base)
    late["features"]["team_epa"]["observed_at"] = "2026-10-04T19:00:00Z"
    for bad in (both, late):
        with pytest.raises(ValidationError):
            FeatureSnapshot.model_validate(bad)
