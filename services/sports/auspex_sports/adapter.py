"""SportAdapter contract and the coverage-boundary checks shared by sport implementations.

Each sport supplies a ``CoverageBoundary`` (data, not code): which leagues, market types, sides,
lines, features, and settlement confirmations it supports. Anything outside the boundary, or
missing/stale evidence, yields INSUFFICIENT_DATA. No sport has a validated model yet, so
``estimate_leg`` returns INSUFFICIENT_DATA even for covered legs.

Deferred from the prompt.md adapter sketch until their inputs exist: ``normalize_market``
(raw provider markets, research stream), ``collect_features`` (provider retrieval), and
``simulate_combo`` (needs a validated correlation model).
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Protocol

from auspex_contracts import BetLeg, MarketType, Side, Sport
from auspex_prediction.core import (
    InsufficientData,
    pregame_blockers,
    require_aware,
    require_probability,
)


@dataclass(frozen=True)
class FeatureObservation:
    value: str | Decimal | None  # None = source reported the feature as unknown
    observed_at_utc: datetime
    source_ref: str  # evidence snapshot or source identifier backing this value


@dataclass(frozen=True)
class FeatureSnapshot:
    captured_at_utc: datetime
    features: Mapping[str, FeatureObservation]


@dataclass(frozen=True)
class MarketRule:
    sides: frozenset[Side]
    required_features: tuple[str, ...]
    settlement_requirements: tuple[str, ...]
    requires_line: bool = False
    line_step: Decimal | None = None  # line must be a multiple of this
    allowed_lines: frozenset[Decimal] | None = None
    positive_line_only: bool = False


@dataclass(frozen=True)
class CoverageBoundary:
    sport: Sport
    leagues: frozenset[str]
    markets: Mapping[MarketType, MarketRule]
    max_feature_age: timedelta
    exclusions: tuple[str, ...]  # documented out-of-scope markets, shown to the user


@dataclass(frozen=True)
class CoverageResult:
    reasons: tuple[str, ...]  # empty means covered

    @property
    def covered(self) -> bool:
        return not self.reasons

    def insufficient(self) -> InsufficientData | None:
        return InsufficientData(self.reasons) if self.reasons else None


@dataclass(frozen=True)
class LegEstimate:
    model_probability: Decimal
    probability_low: Decimal
    probability_high: Decimal
    model_version: str
    snapshot_captured_at_utc: datetime

    def __post_init__(self) -> None:
        for name in ("model_probability", "probability_low", "probability_high"):
            require_probability(name, getattr(self, name))
        if not self.probability_low <= self.model_probability <= self.probability_high:
            raise ValueError(
                "model_probability must lie within [probability_low, probability_high]"
            )
        if not self.model_version:
            raise ValueError("model_version is required")
        require_aware("snapshot_captured_at_utc", self.snapshot_captured_at_utc)


class SportAdapter(Protocol):
    @property
    def sport(self) -> Sport: ...

    @property
    def coverage(self) -> CoverageBoundary: ...

    def validate_coverage(
        self, leg: BetLeg, snapshot: FeatureSnapshot | None, as_of_utc: datetime
    ) -> CoverageResult: ...

    def estimate_leg(
        self, leg: BetLeg, snapshot: FeatureSnapshot | None, as_of_utc: datetime
    ) -> LegEstimate | InsufficientData: ...

    def settlement_requirements(self, leg: BetLeg) -> tuple[str, ...]: ...


def _line_reasons(leg: BetLeg, rule: MarketRule) -> list[str]:
    line = leg.line
    if not rule.requires_line:
        return [] if line is None else [f"{leg.market_type.value} must not carry a line"]
    if line is None:
        return [f"{leg.market_type.value} requires a line"]
    if rule.positive_line_only and line <= 0:
        return [f"line {line} must be positive"]
    if rule.line_step is not None and line % rule.line_step != 0:
        return [f"line {line} is not a multiple of {rule.line_step}"]
    if rule.allowed_lines is not None and line not in rule.allowed_lines:
        return [f"line {line} outside supported lines {sorted(rule.allowed_lines)}"]
    return []


def _feature_reasons(
    snapshot: FeatureSnapshot | None,
    required: tuple[str, ...],
    as_of_utc: datetime,
    max_age: timedelta,
) -> list[str]:
    if snapshot is None:
        return ["no feature snapshot"] if required else []
    out: list[str] = []
    for name in required:
        obs = snapshot.features.get(name)
        if obs is None or obs.value is None:
            out.append(f"missing feature {name}")
            continue
        age = as_of_utc - require_aware(f"{name}.observed_at_utc", obs.observed_at_utc)
        if age < timedelta(0):
            out.append(f"feature {name} observed after as_of_utc")
        elif age > max_age:
            out.append(f"feature {name} is stale ({age} old; limit {max_age})")
    return out


@dataclass(frozen=True)
class CoverageBoundedAdapter:
    """Adapter driven entirely by a ``CoverageBoundary``; no probability model registered."""

    coverage: CoverageBoundary

    @property
    def sport(self) -> Sport:
        return self.coverage.sport

    def validate_coverage(
        self, leg: BetLeg, snapshot: FeatureSnapshot | None, as_of_utc: datetime
    ) -> CoverageResult:
        b = self.coverage
        if leg.sport is not b.sport:
            return CoverageResult((f"leg sport {leg.sport.value} is not {b.sport.value}",))
        if leg.league not in b.leagues:
            return CoverageResult((f"league {leg.league!r} not in coverage {sorted(b.leagues)}",))
        rule = b.markets.get(leg.market_type)
        if rule is None:
            return CoverageResult(
                (f"{b.sport.value} {leg.market_type.value} is outside coverage", *b.exclusions)
            )
        reasons = pregame_blockers(leg, as_of_utc)
        if leg.side not in rule.sides:
            reasons.append(f"side {leg.side.value} invalid for {leg.market_type.value}")
        reasons += _line_reasons(leg, rule)
        if not leg.settlement_rule_ref:
            reasons.append("settlement rule not confirmed (settlement_rule_ref missing)")
        reasons += _feature_reasons(snapshot, rule.required_features, as_of_utc, b.max_feature_age)
        return CoverageResult(tuple(reasons))

    def estimate_leg(
        self, leg: BetLeg, snapshot: FeatureSnapshot | None, as_of_utc: datetime
    ) -> LegEstimate | InsufficientData:
        blocked = self.validate_coverage(leg, snapshot, as_of_utc).insufficient()
        if blocked is not None:
            return blocked
        return InsufficientData(
            (f"no validated {self.sport.value} {leg.market_type.value} model is registered",)
        )

    def settlement_requirements(self, leg: BetLeg) -> tuple[str, ...]:
        rule = self.coverage.markets.get(leg.market_type)
        return rule.settlement_requirements if rule else ()
