from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from auspex_contracts import MarketType, Sport
from auspex_prediction.core import InsufficientData
from auspex_prediction.evaluation import EvaluationArtifact, Prediction, compare_to_baseline
from auspex_prediction.registry import (
    InMemoryModelRegistry,
    ModelMetadata,
    ModelStatus,
    TrainingProvenance,
)

T0 = datetime(2026, 1, 1, tzinfo=UTC)


def p(x: str, o: bool) -> Prediction:
    return Prediction(D(x), o)


def artifact(*, minimum: int = 2, version: str = "v1", code: str = "abc") -> EvaluationArtifact:
    cmp = compare_to_baseline(
        [p("0.9", True), p("0.1", False)], [p("0.5", True), p("0.5", False)], minimum=minimum
    )
    assert not isinstance(cmp, InsufficientData)
    return EvaluationArtifact(
        artifact_id="ev-1",
        model_version=version,
        code_version=code,
        dataset_ref="holdout",
        evaluated_at_utc=T0,
        comparison=cmp,
        baseline_name="devig-consensus",
        log_loss=D("0.2"),
        calibration=(),
    )


def meta(**kw: object) -> ModelMetadata:
    base: dict[str, object] = {
        "model_id": "nfl-ml",
        "version": "v1",
        "code_version": "abc",
        "sport": Sport.NFL,
        "leagues": frozenset({"NFL"}),
        "market_types": frozenset({MarketType.MONEYLINE}),
        "max_interval_width": D("0.2"),
        "training": TrainingProvenance("train-2018-2024", T0, "2018..2024"),
    }
    return ModelMetadata(**(base | kw))  # type: ignore[arg-type]


def test_default_status_is_registered_and_never_active() -> None:
    reg = InMemoryModelRegistry([meta()])
    assert reg.get("nfl-ml", "v1") is not None
    assert reg.active_for(Sport.NFL, "NFL", MarketType.MONEYLINE) is None


def test_active_requires_matching_adequate_artifact() -> None:
    with pytest.raises(ValueError, match="requires an evaluation"):
        meta(status=ModelStatus.ACTIVE)
    with pytest.raises(ValueError, match="does not match"):
        meta(status=ModelStatus.ACTIVE, evaluation=artifact(version="v0"))
    with pytest.raises(ValueError, match="does not match"):
        meta(status=ModelStatus.ACTIVE, evaluation=artifact(code="zzz"))
    with pytest.raises(ValueError, match="adequate sample"):
        meta(status=ModelStatus.ACTIVE, evaluation=artifact(minimum=5))


def test_active_model_is_found_by_coverage() -> None:
    active = meta(status=ModelStatus.ACTIVE, evaluation=artifact())
    reg = InMemoryModelRegistry([active])
    assert reg.active_for(Sport.NFL, "NFL", MarketType.MONEYLINE) is active
    assert reg.active_for(Sport.NFL, "NFL", MarketType.TOTAL) is None
    assert reg.active_for(Sport.MLB, "NFL", MarketType.MONEYLINE) is None


def test_versions_immutable_and_single_active_per_coverage() -> None:
    reg = InMemoryModelRegistry([meta()])
    with pytest.raises(ValueError, match="already registered"):
        reg.register(meta())
    reg.register(meta(version="v2", evaluation=artifact(version="v2"), status=ModelStatus.ACTIVE))
    with pytest.raises(ValueError, match="already covers"):
        reg.register(
            meta(version="v3", evaluation=artifact(version="v3"), status=ModelStatus.ACTIVE)
        )


def test_metadata_validation() -> None:
    with pytest.raises(ValueError, match="code_version"):
        meta(code_version="")
    with pytest.raises(ValueError, match="league"):
        meta(leagues=frozenset())
    with pytest.raises(ValueError, match="dataset_ref"):
        TrainingProvenance("", T0, "w")
    assert replace(meta(), status=ModelStatus.SHADOW).status is ModelStatus.SHADOW
