from datetime import UTC, datetime, timedelta
from decimal import Decimal as D

import pytest

from auspex_contracts import BetLeg, MarketType, Side, Sport
from auspex_prediction.core import InsufficientData
from auspex_prediction.evaluation import EvaluationArtifact, Prediction, compare_to_baseline
from auspex_prediction.registry import (
    InMemoryModelRegistry,
    ModelMetadata,
    ModelStatus,
    TrainingProvenance,
)
from auspex_prediction.uncertainty import ConfidenceTier, ProbabilityInterval
from auspex_sports.adapter import FeatureObservation, FeatureSnapshot, LegEstimate
from auspex_sports.estimator import EstimationContext, estimate_leg
from auspex_sports.nfl import NFL_ADAPTER, NFL_COVERAGE

NOW = datetime(2026, 9, 21, 12, tzinfo=UTC)
T0 = datetime(2026, 1, 1, tzinfo=UTC)
FEATURES = NFL_COVERAGE.markets[MarketType.MONEYLINE].required_features


def leg() -> BetLeg:
    return BetLeg(
        sport=Sport.NFL,
        league="NFL",
        event_id="g1",
        event_start_utc=NOW + timedelta(hours=4),
        home_participant="Chiefs",
        away_participant="Bills",
        market_type=MarketType.MONEYLINE,
        side=Side.HOME,
        market_price_usd=D("0.55"),
        settlement_rule_ref="pm-us/nfl-moneyline-v1",
    )


def snap(age: timedelta = timedelta(hours=1), sources: int = 2) -> FeatureSnapshot:
    return FeatureSnapshot(
        NOW,
        {
            n: FeatureObservation("known", NOW - age, f"evidence:{i % sources}")
            for i, n in enumerate(FEATURES)
        },
    )


def p(x: str, o: bool) -> Prediction:
    return Prediction(D(x), o)


def metadata(*, active: bool = True, width: str = "0.2") -> ModelMetadata:
    cmp = compare_to_baseline(
        [p("0.9", True), p("0.1", False)], [p("0.5", True), p("0.5", False)], minimum=2
    )
    assert not isinstance(cmp, InsufficientData)
    art = EvaluationArtifact(
        "ev-1", "v1", "abc", "holdout", T0, cmp, "devig-consensus", D("0.2"), ()
    )
    return ModelMetadata(
        model_id="nfl-ml",
        version="v1",
        code_version="abc",
        sport=Sport.NFL,
        leagues=frozenset({"NFL"}),
        market_types=frozenset({MarketType.MONEYLINE}),
        max_interval_width=D(width),
        training=TrainingProvenance("train", T0, "2018..2024"),
        status=ModelStatus.ACTIVE if active else ModelStatus.REGISTERED,
        evaluation=art if active else None,
    )


class Fixed:
    def __init__(self, interval: ProbabilityInterval) -> None:
        self.interval = interval
        self.calls = 0

    def predict(self, leg: BetLeg, snapshot: FeatureSnapshot) -> ProbabilityInterval:
        self.calls += 1
        return self.interval


def iv(point: str = "0.6", low: str = "0.55", high: str = "0.65") -> ProbabilityInterval:
    return ProbabilityInterval(D(point), D(low), D(high))


def ctx(predictor: Fixed | None, meta: ModelMetadata | None) -> EstimationContext:
    return EstimationContext(
        NFL_ADAPTER,
        InMemoryModelRegistry([meta] if meta else []),
        {("nfl-ml", "v1"): predictor} if predictor else {},
    )


def test_happy_path_carries_full_provenance() -> None:
    pred = Fixed(iv())
    out = estimate_leg(ctx(pred, metadata()), leg(), snap(), NOW)
    assert isinstance(out, LegEstimate)
    assert (out.model_id, out.model_version, out.code_version) == ("nfl-ml", "v1", "abc")
    assert out.evaluation_artifact_id == "ev-1"
    assert out.snapshot_captured_at_utc == NOW and out.as_of_utc == NOW
    assert out.model_probability == D("0.6")
    assert out.evidence_confidence is ConfidenceTier.HIGH  # 1h of 12h, two sources
    assert out.prediction_confidence is ConfidenceTier.HIGH  # width 0.10


def test_evidence_and_prediction_confidence_differ() -> None:
    wide = Fixed(iv("0.6", "0.5", "0.7"))  # width 0.2 -> MEDIUM prediction
    out = estimate_leg(ctx(wide, metadata()), leg(), snap(timedelta(hours=11), sources=1), NOW)
    assert isinstance(out, LegEstimate)
    assert out.evidence_confidence is ConfidenceTier.LOW
    assert out.prediction_confidence is ConfidenceTier.MEDIUM


def test_no_snapshot_or_stale_or_missing_never_reaches_model() -> None:
    pred = Fixed(iv())
    c = ctx(pred, metadata())
    assert isinstance(estimate_leg(c, leg(), None, NOW), InsufficientData)
    stale = estimate_leg(c, leg(), snap(timedelta(hours=13)), NOW)
    assert isinstance(stale, InsufficientData) and "stale" in stale.reasons[0]
    partial = FeatureSnapshot(NOW, {FEATURES[0]: snap().features[FEATURES[0]]})
    assert isinstance(estimate_leg(c, leg(), partial, NOW), InsufficientData)
    assert pred.calls == 0


def test_no_active_model_or_inactive_model_abstains() -> None:
    pred = Fixed(iv())
    for meta in (None, metadata(active=False)):
        out = estimate_leg(ctx(pred, meta), leg(), snap(), NOW)
        assert isinstance(out, InsufficientData) and "no active evaluated model" in out.reasons[0]
    assert pred.calls == 0


def test_missing_predictor_abstains() -> None:
    out = estimate_leg(ctx(None, metadata()), leg(), snap(), NOW)
    assert isinstance(out, InsufficientData) and "no predictor" in out.reasons[0]


def test_abstains_on_wide_interval_model_limit_and_global_limit() -> None:
    wide = Fixed(iv("0.6", "0.45", "0.75"))  # width 0.30: over model limit 0.2, at global limit
    out = estimate_leg(ctx(wide, metadata()), leg(), snap(), NOW)
    assert isinstance(out, InsufficientData) and "model limit" in out.reasons[0]
    huge = Fixed(iv("0.6", "0.3", "0.9"))
    out = estimate_leg(ctx(huge, metadata(width="0.9")), leg(), snap(), NOW)
    assert isinstance(out, InsufficientData) and "exceeds limit" in out.reasons[0]


def test_malformed_predictor_output_raises() -> None:
    with pytest.raises(ValueError):
        ProbabilityInterval(D("0.7"), D("0.4"), D("0.6"))


def test_leg_estimate_validation() -> None:
    kw = dict(
        model_probability=D("0.5"),
        probability_low=D("0.4"),
        probability_high=D("0.6"),
        model_id="m",
        model_version="v1",
        code_version="abc",
        evaluation_artifact_id="ev-1",
        snapshot_captured_at_utc=NOW,
        as_of_utc=NOW,
        evidence_confidence=ConfidenceTier.LOW,
        prediction_confidence=ConfidenceTier.LOW,
    )
    assert LegEstimate(**kw).model_id == "m"  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="within"):
        LegEstimate(**{**kw, "model_probability": D("0.7")})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="evaluation_artifact_id"):
        LegEstimate(**{**kw, "evaluation_artifact_id": ""})  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        LegEstimate(**{**kw, "model_probability": 0.5})  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="aware"):
        LegEstimate(**{**kw, "as_of_utc": datetime(2026, 1, 1)})  # type: ignore[arg-type]  # noqa: DTZ001
