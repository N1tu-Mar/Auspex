from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from auspex_contracts import Recommendation as R
from auspex_prediction.core import InsufficientData
from auspex_prediction.correlation import CorrelationWarning, DependencyKind
from auspex_prediction.ev import ExpectedValue
from auspex_prediction.policy import PolicyConfig, recommend
from auspex_prediction.uncertainty import ConfidenceTier as T

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
FRESH = NOW - timedelta(minutes=1)


@dataclass(frozen=True)
class Est:
    model_probability: D = D("0.60")
    probability_low: D = D("0.55")
    evidence_confidence: T = T.HIGH
    prediction_confidence: T = T.MEDIUM


def ev(p: str, break_even: str) -> ExpectedValue:
    return ExpectedValue(D(p), D(break_even), (D(p) - D(break_even)) * 100, D(0), D(0))


def rec(
    est: Est | InsufficientData = Est(),  # noqa: B008
    e: ExpectedValue | None = None,
    observed: datetime | None = FRESH,
    warns: tuple[CorrelationWarning, ...] = (),
    config: PolicyConfig = PolicyConfig(),  # noqa: B008
) -> R:
    return recommend(est, e or ev("0.60", "0.50"), observed, NOW, warns, config).recommendation


def warn(kind: DependencyKind) -> CorrelationWarning:
    return CorrelationWarning(kind, (0, 1), "x")


def test_consider_on_clear_edge() -> None:
    assert rec() is R.CONSIDER


def test_insufficient_data_propagates() -> None:
    assert rec(InsufficientData(("no model",))) is R.INSUFFICIENT_DATA


def test_missing_or_future_market_time_is_insufficient() -> None:
    assert rec(observed=None) is R.INSUFFICIENT_DATA
    assert rec(observed=NOW + timedelta(seconds=1)) is R.INSUFFICIENT_DATA


def test_stale_market_avoids_boundary_inclusive() -> None:
    assert rec(observed=NOW - timedelta(minutes=15)) is R.CONSIDER
    assert rec(observed=NOW - timedelta(minutes=15, seconds=1)) is R.AVOID


def test_consider_threshold_boundary() -> None:
    # conservative edge = low - break_even; exactly 0.02 considers, just under passes
    assert rec(Est(probability_low=D("0.52")), ev("0.60", "0.50")) is R.CONSIDER
    assert rec(Est(probability_low=D("0.5199")), ev("0.60", "0.50")) is R.PASS


def test_wide_interval_low_bound_blocks_consider_despite_point_edge() -> None:
    assert rec(Est(probability_low=D("0.40"))) is R.PASS


def test_avoid_boundary_on_negative_point_edge() -> None:
    est = Est(D("0.45"), D("0.40"))
    assert rec(est, ev("0.45", "0.50")) is R.AVOID  # exactly -0.05
    assert rec(est, ev("0.45", "0.4999")) is R.PASS  # -0.0499


def test_zero_edge_is_pass() -> None:
    assert rec(Est(D("0.5"), D("0.45")), ev("0.5", "0.5")) is R.PASS


def test_confidence_gates() -> None:
    assert rec(Est(evidence_confidence=T.LOW)) is R.PASS
    strict = PolicyConfig(min_prediction_confidence=T.HIGH)
    assert rec(Est(prediction_confidence=T.MEDIUM), config=strict) is R.PASS


def test_correlation_rules() -> None:
    assert rec(warns=(warn(DependencyKind.SHARED_GAME),)) is R.PASS
    assert rec(warns=(warn(DependencyKind.SAME_MARKET),)) is R.AVOID
    assert rec(warns=(warn(DependencyKind.UNKNOWN_DEPENDENCY),)) is R.INSUFFICIENT_DATA


def test_mismatched_ev_and_estimate_raises() -> None:
    with pytest.raises(ValueError, match="different probability"):
        rec(Est(), ev("0.70", "0.50"))


def test_config_validation() -> None:
    with pytest.raises(ValueError):
        PolicyConfig(min_conservative_edge=D(0))
    with pytest.raises(ValueError):
        PolicyConfig(avoid_point_edge=D("0.01"))
    with pytest.raises(ValueError):
        PolicyConfig(max_market_age=timedelta(0))
