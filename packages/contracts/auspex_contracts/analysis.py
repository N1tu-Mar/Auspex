"""Analysis-facing contracts: per-leg estimates, combo assessment, recommendation, analysis run.

Promoted from internal dataclasses in `services/prediction` and `services/sports`. All
probabilities are unitless in [0, 1], money is USD, and every `Decimal` serializes as a string.
An analysis run is immutable: re-analysis inserts a new run with a later `as_of_utc`.
"""

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal, Self
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, field_validator, model_validator

from auspex_contracts._base import Contract
from auspex_contracts.bet_slip import PositiveUsd, Recommendation

Probability = Annotated[Decimal, Field(ge=0, le=1)]


class InsufficientData(Contract):
    """No responsible estimate is possible; `reasons` says why, in plain language."""

    reasons: tuple[str, ...] = Field(min_length=1)
    status: Literal[Recommendation.INSUFFICIENT_DATA] = Recommendation.INSUFFICIENT_DATA


class UncertaintyInterval(Contract):
    low: Probability
    high: Probability

    @model_validator(mode="after")
    def _ordered(self) -> Self:
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class LegEstimate(Contract):
    model_probability: Probability
    interval: UncertaintyInterval
    model_version: str = Field(min_length=1)
    snapshot_captured_at_utc: AwareDatetime

    @field_validator("snapshot_captured_at_utc")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _within_interval(self) -> Self:
        if not self.interval.low <= self.model_probability <= self.interval.high:
            raise ValueError("model_probability must lie within the interval")
        return self


class DependencyKind(StrEnum):
    SHARED_GAME = "SHARED_GAME"
    SAME_MARKET = "SAME_MARKET"  # same game and market type: nested or mutually exclusive
    SHARED_TEAM = "SHARED_TEAM"
    SHARED_PLAYER = "SHARED_PLAYER"
    SHARED_WEATHER = "SHARED_WEATHER"
    GAME_SCRIPT = "GAME_SCRIPT"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"  # not enough identifiers to rule dependency out


class CorrelationWarning(Contract):
    kind: DependencyKind
    leg_indices: tuple[int, ...] = Field(min_length=1)
    explanation: str = Field(min_length=1)
    magnitude: Literal["UNQUANTIFIED"] = "UNQUANTIFIED"  # no validated correlation model yet


class NaiveIndependentBaseline(Contract):
    """Product of leg probabilities. A comparison baseline only, never a recommendation input."""

    probability: Probability
    label: Literal["NAIVE_INDEPENDENT_BASELINE"] = "NAIVE_INDEPENDENT_BASELINE"
    assumption: str = "treats legs as independent; wrong whenever legs share a dependency"


class ComboAssessment(Contract):
    naive_baseline: NaiveIndependentBaseline
    warnings: tuple[CorrelationWarning, ...] = ()
    # Correlation-aware joint probability; INSUFFICIENT_DATA until a validated model exists.
    joint_probability: InsufficientData


class PositionCosts(Contract):
    stake_usd: PositiveUsd
    gross_payout_usd: PositiveUsd
    estimated_fees_usd: Annotated[Decimal, Field(ge=0)]
    estimated_slippage_usd: Annotated[Decimal, Field(ge=0)]


class ExpectedValue(Contract):
    costs: PositionCosts
    model_probability: Probability
    break_even_probability: Decimal = Field(description="May exceed 1: no probability breaks even.")
    edge_probability_points: Decimal
    expected_profit_usd: Decimal
    expected_return_pct: Decimal


class RecommendationResult(Contract):
    recommendation: Recommendation
    reason: str = Field(min_length=1, description="One sentence.")
    insufficient_data: InsufficientData | None = None

    @model_validator(mode="after")
    def _reasons_iff_insufficient(self) -> Self:
        if (self.recommendation is Recommendation.INSUFFICIENT_DATA) != (
            self.insufficient_data is not None
        ):
            raise ValueError("insufficient_data must be set exactly when INSUFFICIENT_DATA")
        return self


class LegAnalysis(Contract):
    """One leg's result plus the exact snapshots it was computed from."""

    leg_index: int = Field(ge=0)
    market_implied_probability: Probability
    consensus_probability: Probability | None = Field(
        default=None, description="De-vigged external consensus, when books were available."
    )
    estimate: LegEstimate | None = None
    insufficient_data: InsufficientData | None = None
    edge_probability_points: Decimal | None = None
    event_snapshot_id: UUID | None = None
    market_snapshot_id: UUID | None = None
    evidence_snapshot_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    feature_snapshot_id: UUID | None = None

    @model_validator(mode="after")
    def _estimate_xor_insufficient(self) -> Self:
        if (self.estimate is None) == (self.insufficient_data is None):
            raise ValueError("set exactly one of estimate or insufficient_data")
        if (self.edge_probability_points is None) != (self.estimate is None):
            raise ValueError("edge_probability_points is set exactly when an estimate exists")
        return self


class AnalysisRun(Contract):
    """Complete, auditable record of one analysis of one saved slip. Immutable once stored."""

    id: UUID = Field(default_factory=uuid4)
    created_at: AwareDatetime
    as_of_utc: AwareDatetime = Field(description="Data cutoff: nothing newer was used.")
    bet_slip_id: UUID
    intake_record_id: UUID | None = None
    code_version: str = Field(min_length=1, description="Git commit of the analysis code.")
    model_version: str = Field(min_length=1)
    legs: tuple[LegAnalysis, ...] = Field(min_length=1)
    combo: ComboAssessment | None = Field(default=None, description="Set only for 2+ legs.")
    expected_value: ExpectedValue | None = None
    recommendation: RecommendationResult

    @field_validator("created_at", "as_of_utc")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if [leg.leg_index for leg in self.legs] != list(range(len(self.legs))):
            raise ValueError("leg_index values must be 0..n-1 in order")
        if self.as_of_utc > self.created_at:
            raise ValueError("as_of_utc is after created_at")
        if (self.combo is not None) != (len(self.legs) > 1):
            raise ValueError("combo is set exactly when the slip has 2+ legs")
        if self.recommendation.recommendation is Recommendation.CONSIDER and (
            self.expected_value is None or any(leg.estimate is None for leg in self.legs)
        ):
            raise ValueError("CONSIDER requires an estimate for every leg and expected_value")
        return self


class AnalysisRef(Contract):
    """Stable reference a future paper trade points at; carries no paper-trade behavior."""

    analysis_id: UUID
    bet_slip_id: UUID
    as_of_utc: AwareDatetime
    recommendation: Recommendation
