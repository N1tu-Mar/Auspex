from datetime import UTC, datetime
from decimal import Decimal as D

import pytest

from auspex_prediction.core import InsufficientData
from auspex_prediction.evaluation import (
    EvaluationArtifact,
    PaperPosition,
    Prediction,
    brier_score,
    calibration_bins,
    compare_to_baseline,
    log_loss,
    roi,
    sample_size_warnings,
)


def preds(*pairs: tuple[str, bool]) -> list[Prediction]:
    return [Prediction(D(p), o) for p, o in pairs]


def test_brier_exact() -> None:
    # (0.8-1)^2=0.04 ; (0.3-0)^2=0.09 ; mean 0.065
    assert brier_score(preds(("0.8", True), ("0.3", False))) == D("0.065")


def test_brier_and_log_loss_empty_is_insufficient() -> None:
    assert isinstance(brier_score([]), InsufficientData)
    assert isinstance(log_loss([]), InsufficientData)
    assert isinstance(roi([]), InsufficientData)


def test_log_loss_known_value_and_deterministic() -> None:
    ll = log_loss(preds(("0.5", True), ("0.5", False)))
    assert isinstance(ll, D)
    assert abs(ll - D(2).ln() + D(0)) < D("1e-20")
    assert ll == log_loss(preds(("0.5", True), ("0.5", False)))


def test_log_loss_clips_certain_wrong_prediction() -> None:
    ll = log_loss(preds(("1", False)))
    assert isinstance(ll, D)
    assert ll.is_finite() and ll > 30


def test_prediction_validation() -> None:
    with pytest.raises(TypeError):
        Prediction(0.5, True)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        Prediction(D("1.1"), True)
    with pytest.raises(TypeError):
        Prediction(D("0.5"), 1)  # type: ignore[arg-type]


def test_roi() -> None:
    ps = [PaperPosition(D(10), D(5)), PaperPosition(D(10), D(-10))]
    assert roi(ps) == D("-0.25")
    with pytest.raises(ValueError):
        PaperPosition(D(0), D(1))


def test_calibration_bins_suppress_small_bins() -> None:
    data = preds(*[("0.85", True)] * 3, *[("0.85", False)], ("1", True))
    bins = calibration_bins(data, n_bins=10, min_bin_sample=4)
    assert len(bins) == 10
    b8, b9 = bins[8], bins[9]
    assert (b8.count, b8.suppressed, b8.observed_frequency) == (4, False, D("0.75"))
    assert b8.mean_predicted == D("0.85")
    assert (b9.count, b9.suppressed, b9.observed_frequency) == (1, True, None)  # p=1 -> last bin
    assert bins[0].count == 0 and bins[0].mean_predicted is None and bins[0].suppressed


def test_sample_size_warnings() -> None:
    assert sample_size_warnings(10, 300)
    assert sample_size_warnings(300, 300) == ()


def test_baseline_comparison_suppressed_when_small() -> None:
    model = preds(("0.9", True), ("0.1", False))
    base = preds(("0.5", True), ("0.5", False))
    res = compare_to_baseline(model, base, minimum=5)
    assert not isinstance(res, InsufficientData)
    assert res.beats_baseline is None and res.warnings
    assert res.model_brier == D("0.01") and res.baseline_brier == D("0.25")
    assert res.brier_skill == D("0.96")


def test_baseline_comparison_with_adequate_sample() -> None:
    model = preds(("0.9", True), ("0.1", False))
    worse = preds(("0.5", True), ("0.5", False))
    ok = compare_to_baseline(model, worse, minimum=2)
    assert not isinstance(ok, InsufficientData) and ok.beats_baseline is True
    lose = compare_to_baseline(worse, model, minimum=2)
    assert not isinstance(lose, InsufficientData) and lose.beats_baseline is False


def test_baseline_comparison_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        compare_to_baseline(preds(("0.5", True)), preds(("0.5", False)))
    with pytest.raises(ValueError):
        compare_to_baseline(preds(("0.5", True)), [])
    assert isinstance(compare_to_baseline([], []), InsufficientData)


def test_artifact_requires_fields_and_adequate_win() -> None:
    model = preds(("0.9", True), ("0.1", False))
    base = preds(("0.5", True), ("0.5", False))
    cmp_ok = compare_to_baseline(model, base, minimum=2)
    assert not isinstance(cmp_ok, InsufficientData)
    kw = dict(
        artifact_id="ev-1",
        model_version="v1",
        code_version="abc",
        dataset_ref="holdout-2025",
        evaluated_at_utc=datetime(2026, 1, 1, tzinfo=UTC),
        baseline_name="devig-consensus",
        log_loss=D("0.3"),
        calibration=(),
    )
    art = EvaluationArtifact(comparison=cmp_ok, **kw)  # type: ignore[arg-type]
    assert art.supports_activation
    small = compare_to_baseline(model, base, minimum=5)
    assert not isinstance(small, InsufficientData)
    assert not EvaluationArtifact(comparison=small, **kw).supports_activation  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="dataset_ref"):
        EvaluationArtifact(comparison=cmp_ok, **{**kw, "dataset_ref": ""})  # type: ignore[arg-type]
