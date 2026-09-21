"""Deterministic leg-estimate orchestration.

Returns a well-provenanced ``LegEstimate`` only when every gate passes: coverage (sport boundary,
typed and fresh features), an ACTIVE evaluated model in the registry, a predictor for it, a valid
interval, and an interval narrow enough to avoid abstention. Anything else is ``InsufficientData``.
A predictor that returns a malformed interval is a bug and raises ``ValueError``.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol

from auspex_contracts import BetLeg
from auspex_prediction.core import InsufficientData
from auspex_prediction.registry import ModelMetadata, ModelRegistry
from auspex_prediction.uncertainty import (
    ConfidenceTier,
    ProbabilityInterval,
    UncertaintyPolicy,
    abstain_if_too_wide,
    evidence_confidence,
    prediction_confidence,
)
from auspex_sports.adapter import FeatureSnapshot, LegEstimate, SportAdapter


class Predictor(Protocol):
    def predict(self, leg: BetLeg, snapshot: FeatureSnapshot) -> ProbabilityInterval: ...


PredictorKey = tuple[str, str]  # (model_id, version)


@dataclass(frozen=True)
class EstimationContext:
    adapter: SportAdapter
    registry: ModelRegistry
    predictors: Mapping[PredictorKey, Predictor]
    policy: UncertaintyPolicy = UncertaintyPolicy()  # noqa: RUF009 - frozen dataclass


def _evidence_tier(
    ctx: EstimationContext, leg: BetLeg, snapshot: FeatureSnapshot, as_of_utc: datetime
) -> ConfidenceTier:
    rule = ctx.adapter.coverage.markets[leg.market_type]
    obs = [snapshot.features[n] for n in rule.required_features]
    limit = ctx.adapter.coverage.max_feature_age
    oldest = max((as_of_utc - o.observed_at_utc for o in obs), default=limit * 0)
    return evidence_confidence(
        max_age_fraction=Decimal(oldest / limit),
        distinct_sources=len({o.source_ref for o in obs}) or 1,
        policy=ctx.policy,
    )


def estimate_leg(
    ctx: EstimationContext,
    leg: BetLeg,
    snapshot: FeatureSnapshot | None,
    as_of_utc: datetime,
) -> LegEstimate | InsufficientData:
    blocked = ctx.adapter.validate_coverage(leg, snapshot, as_of_utc).insufficient()
    if blocked is not None:
        return blocked
    if snapshot is None:  # only reachable when a market requires no features
        return InsufficientData(("no feature snapshot",))
    meta = ctx.registry.active_for(leg.sport, leg.league, leg.market_type)
    if meta is None or meta.evaluation is None:
        return InsufficientData(
            (f"no active evaluated model for {leg.league} {leg.market_type.value}",)
        )
    predictor = ctx.predictors.get((meta.model_id, meta.version))
    if predictor is None:
        return InsufficientData((f"no predictor bound for {meta.model_id} {meta.version}",))
    interval = predictor.predict(leg, snapshot)
    wide = _abstain(interval, meta, ctx.policy)
    if wide is not None:
        return wide
    return LegEstimate(
        model_probability=interval.point,
        probability_low=interval.low,
        probability_high=interval.high,
        model_id=meta.model_id,
        model_version=meta.version,
        code_version=meta.code_version,
        evaluation_artifact_id=meta.evaluation.artifact_id,
        snapshot_captured_at_utc=snapshot.captured_at_utc,
        as_of_utc=as_of_utc,
        evidence_confidence=_evidence_tier(ctx, leg, snapshot, as_of_utc),
        prediction_confidence=prediction_confidence(
            interval, ctx.policy, validated_sample=meta.evaluation.supports_activation
        ),
    )


def _abstain(
    interval: ProbabilityInterval, meta: ModelMetadata, policy: UncertaintyPolicy
) -> InsufficientData | None:
    if interval.width > meta.max_interval_width:
        return InsufficientData(
            (f"interval width {interval.width} exceeds model limit {meta.max_interval_width}",)
        )
    return abstain_if_too_wide(interval, policy)
