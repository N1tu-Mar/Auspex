from decimal import Decimal as D

import pytest

from auspex_prediction.core import InsufficientData
from auspex_prediction.uncertainty import (
    ConfidenceTier as T,
)
from auspex_prediction.uncertainty import (
    ProbabilityInterval,
    UncertaintyPolicy,
    abstain_if_too_wide,
    evidence_confidence,
    prediction_confidence,
)

POLICY = UncertaintyPolicy()


@pytest.mark.parametrize(
    ("point", "low", "high"),
    [("0.7", "0.4", "0.6"), ("0.3", "0.4", "0.6"), ("0.5", "-0.1", "0.6"), ("0.5", "0.4", "1.1")],
)
def test_invalid_intervals_raise(point: str, low: str, high: str) -> None:
    with pytest.raises(ValueError):
        ProbabilityInterval(D(point), D(low), D(high))


def test_interval_rejects_float() -> None:
    with pytest.raises(TypeError):
        ProbabilityInterval(0.5, D("0.4"), D("0.6"))  # type: ignore[arg-type]


def test_degenerate_interval_allowed_width_zero() -> None:
    assert ProbabilityInterval(D("0.5"), D("0.5"), D("0.5")).width == 0


def test_abstain_boundary_is_inclusive_of_limit() -> None:
    at = ProbabilityInterval(D("0.5"), D("0.35"), D("0.65"))  # width 0.30 == limit
    assert abstain_if_too_wide(at, POLICY) is None
    over = ProbabilityInterval(D("0.5"), D("0.349"), D("0.65"))
    assert isinstance(abstain_if_too_wide(over, POLICY), InsufficientData)


def test_prediction_confidence_tiers() -> None:
    def tier(w: str, sample: bool = True) -> T:
        i = ProbabilityInterval(D("0.5"), D("0.5") - D(w) / 2, D("0.5") + D(w) / 2)
        return prediction_confidence(i, POLICY, validated_sample=sample)

    assert tier("0.10") is T.HIGH
    assert tier("0.11") is T.MEDIUM
    assert tier("0.20") is T.MEDIUM
    assert tier("0.21") is T.LOW
    assert tier("0.02", sample=False) is T.LOW  # unvalidated sample caps at LOW


def test_evidence_confidence_is_independent_of_interval() -> None:
    def ev(frac: str, n: int) -> T:
        return evidence_confidence(max_age_fraction=D(frac), distinct_sources=n, policy=POLICY)

    assert ev("0.5", 2) is T.HIGH
    assert ev("0.5", 1) is T.MEDIUM
    assert ev("0.9", 3) is T.MEDIUM
    assert ev("0.9", 1) is T.LOW
    with pytest.raises(ValueError):
        ev("1.1", 1)
    with pytest.raises(ValueError):
        ev("0.1", 0)


def test_policy_widths_validated() -> None:
    with pytest.raises(ValueError):
        UncertaintyPolicy(max_interval_width=D("0.05"))
