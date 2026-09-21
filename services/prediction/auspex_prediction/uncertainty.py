"""Probability intervals, confidence tiers, and abstention rules.

Evidence confidence (how complete, fresh, and corroborated the inputs are) and prediction
confidence (how tight and validated the model's output is) are separate tiers and are never
combined into one number. Thresholds are conservative policy defaults, not calibrated values.
"""

from dataclasses import dataclass
from decimal import Decimal
from enum import IntEnum

from auspex_prediction.core import InsufficientData, require_decimal, require_probability


class ConfidenceTier(IntEnum):
    LOW = 1
    MEDIUM = 2
    HIGH = 3


@dataclass(frozen=True)
class ProbabilityInterval:
    """``low <= point <= high``, all in [0, 1]. Malformed intervals raise ``ValueError``."""

    point: Decimal
    low: Decimal
    high: Decimal

    def __post_init__(self) -> None:
        for name in ("point", "low", "high"):
            require_probability(name, getattr(self, name))
        if not self.low <= self.point <= self.high:
            raise ValueError("point must lie within [low, high]")

    @property
    def width(self) -> Decimal:
        return self.high - self.low


@dataclass(frozen=True)
class UncertaintyPolicy:
    max_interval_width: Decimal = Decimal("0.30")  # wider than this: abstain
    high_prediction_width: Decimal = Decimal("0.10")
    medium_prediction_width: Decimal = Decimal("0.20")
    high_evidence_min_sources: int = 2
    high_evidence_max_age_fraction: Decimal = Decimal("0.5")  # of the coverage freshness limit

    def __post_init__(self) -> None:
        widths = (
            self.high_prediction_width,
            self.medium_prediction_width,
            self.max_interval_width,
        )
        for w in widths:
            require_decimal("width", w)
        if not Decimal(0) < widths[0] <= widths[1] <= widths[2] <= Decimal(1):
            raise ValueError("widths must satisfy 0 < high <= medium <= max <= 1")


def abstain_if_too_wide(
    interval: ProbabilityInterval, policy: UncertaintyPolicy
) -> InsufficientData | None:
    if interval.width > policy.max_interval_width:
        return InsufficientData(
            (f"interval width {interval.width} exceeds limit {policy.max_interval_width}",)
        )
    return None


def prediction_confidence(
    interval: ProbabilityInterval, policy: UncertaintyPolicy, *, validated_sample: bool
) -> ConfidenceTier:
    """Tier from interval width. Without an adequately sized evaluation sample, capped at LOW."""
    if not validated_sample or interval.width > policy.medium_prediction_width:
        return ConfidenceTier.LOW
    if interval.width > policy.high_prediction_width:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.HIGH


def evidence_confidence(
    *, max_age_fraction: Decimal, distinct_sources: int, policy: UncertaintyPolicy
) -> ConfidenceTier:
    """Tier from freshness (oldest required feature age / freshness limit) and source diversity.

    Callers must already have passed the coverage gate (all required features present and fresh).
    """
    if max_age_fraction < 0 or max_age_fraction > 1:
        raise ValueError("max_age_fraction must be in [0, 1]")
    if distinct_sources < 1:
        raise ValueError("distinct_sources must be >= 1")
    fresh = max_age_fraction <= policy.high_evidence_max_age_fraction
    if fresh and distinct_sources >= policy.high_evidence_min_sources:
        return ConfidenceTier.HIGH
    if fresh or distinct_sources >= policy.high_evidence_min_sources:
        return ConfidenceTier.MEDIUM
    return ConfidenceTier.LOW
