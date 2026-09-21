"""Recommendation policy: validated estimate, price, freshness, and correlation to a state.

Order of precedence: missing/invalid inputs (INSUFFICIENT_DATA), then AVOID conditions, then
CONSIDER only if the *conservative* edge (interval low bound minus break-even) clears the
threshold with acceptable evidence and prediction confidence, else PASS. Thresholds are
conservative policy defaults, not calibrated values. Boundaries are inclusive: an edge exactly at
the CONSIDER threshold considers; a point edge exactly at the AVOID threshold avoids.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from auspex_contracts import Recommendation
from auspex_prediction.core import InsufficientData, require_aware
from auspex_prediction.correlation import CorrelationWarning, DependencyKind
from auspex_prediction.ev import ExpectedValue
from auspex_prediction.uncertainty import ConfidenceTier


class EstimateLike(Protocol):
    @property
    def model_probability(self) -> Decimal: ...
    @property
    def probability_low(self) -> Decimal: ...
    @property
    def evidence_confidence(self) -> ConfidenceTier: ...
    @property
    def prediction_confidence(self) -> ConfidenceTier: ...


@dataclass(frozen=True)
class PolicyConfig:
    min_conservative_edge: Decimal = Decimal("0.02")  # probability, i.e. 2 points
    avoid_point_edge: Decimal = Decimal("-0.05")
    max_market_age: timedelta = timedelta(minutes=15)
    min_evidence_confidence: ConfidenceTier = ConfidenceTier.MEDIUM
    min_prediction_confidence: ConfidenceTier = ConfidenceTier.LOW

    def __post_init__(self) -> None:
        if self.min_conservative_edge <= 0 or self.avoid_point_edge >= 0:
            raise ValueError("CONSIDER edge must be > 0 and AVOID edge must be < 0")
        if self.max_market_age <= timedelta(0):
            raise ValueError("max_market_age must be positive")


@dataclass(frozen=True)
class PolicyDecision:
    recommendation: Recommendation
    reasons: tuple[str, ...]


def _decide(rec: Recommendation, *reasons: str) -> PolicyDecision:
    return PolicyDecision(rec, reasons)


def recommend(
    estimate: EstimateLike | InsufficientData,
    ev: ExpectedValue,
    market_observed_at_utc: datetime | None,
    as_of_utc: datetime,
    correlation_warnings: Sequence[CorrelationWarning] = (),
    config: PolicyConfig = PolicyConfig(),  # noqa: B008 - frozen dataclass
) -> PolicyDecision:
    require_aware("as_of_utc", as_of_utc)
    if isinstance(estimate, InsufficientData):
        return PolicyDecision(estimate.status, estimate.reasons)
    if ev.model_probability != estimate.model_probability:
        raise ValueError("ev was computed from a different probability than the estimate")
    if market_observed_at_utc is None:
        return _decide(Recommendation.INSUFFICIENT_DATA, "market price has no observation time")
    age = as_of_utc - require_aware("market_observed_at_utc", market_observed_at_utc)
    if age < timedelta(0):
        return _decide(Recommendation.INSUFFICIENT_DATA, "market observation is after as_of_utc")
    if age > config.max_market_age:
        return _decide(Recommendation.AVOID, f"market price is stale ({age} old)")
    kinds = {w.kind for w in correlation_warnings}
    if DependencyKind.UNKNOWN_DEPENDENCY in kinds:
        return _decide(Recommendation.INSUFFICIENT_DATA, "leg dependency cannot be ruled out")
    if DependencyKind.SAME_MARKET in kinds:
        return _decide(Recommendation.AVOID, "legs are nested or mutually exclusive")

    point_edge = ev.model_probability - ev.break_even_probability
    if point_edge <= config.avoid_point_edge:
        return _decide(Recommendation.AVOID, f"price exceeds model probability by {-point_edge}")
    if kinds:
        names = ", ".join(sorted(k.value for k in kinds))
        return _decide(Recommendation.PASS, f"unquantified correlation ({names}) blocks CONSIDER")
    conservative_edge = estimate.probability_low - ev.break_even_probability
    if conservative_edge < config.min_conservative_edge:
        return _decide(
            Recommendation.PASS, f"conservative edge {conservative_edge} below threshold"
        )
    if estimate.evidence_confidence < config.min_evidence_confidence:
        return _decide(Recommendation.PASS, "evidence confidence below threshold")
    if estimate.prediction_confidence < config.min_prediction_confidence:
        return _decide(Recommendation.PASS, "prediction confidence below threshold")
    return _decide(Recommendation.CONSIDER, f"conservative edge {conservative_edge}")
