"""Deterministic model-evaluation primitives. Decimal only; small samples are suppressed."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from auspex_prediction.core import (
    ONE,
    ZERO,
    InsufficientData,
    require_aware,
    require_decimal,
    require_probability,
)

LOG_LOSS_EPSILON = Decimal("1e-15")  # probabilities are clipped to [eps, 1 - eps] before ln
MIN_EVALUATION_SAMPLE = 300  # conservative default; callers may raise but not silently lower
MIN_BIN_SAMPLE = 30


@dataclass(frozen=True)
class Prediction:
    probability: Decimal
    outcome: bool  # True if the leg won

    def __post_init__(self) -> None:
        require_probability("probability", self.probability)
        if not isinstance(self.outcome, bool):
            raise TypeError("outcome must be bool")


def _require_sample(preds: Sequence[Prediction]) -> InsufficientData | None:
    return None if preds else InsufficientData(("no predictions to evaluate",))


def brier_score(preds: Sequence[Prediction]) -> Decimal | InsufficientData:
    empty = _require_sample(preds)
    if empty:
        return empty
    total = sum(((p.probability - (ONE if p.outcome else ZERO)) ** 2 for p in preds), ZERO)
    return total / len(preds)


def log_loss(preds: Sequence[Prediction]) -> Decimal | InsufficientData:
    empty = _require_sample(preds)
    if empty:
        return empty
    lo, hi = LOG_LOSS_EPSILON, ONE - LOG_LOSS_EPSILON
    total = ZERO
    for p in preds:
        q = min(max(p.probability, lo), hi)
        total -= (q if p.outcome else ONE - q).ln()
    return total / len(preds)


@dataclass(frozen=True)
class PaperPosition:
    stake_usd: Decimal
    profit_usd: Decimal  # net of stake, fees, and slippage; may be negative

    def __post_init__(self) -> None:
        if require_decimal("stake_usd", self.stake_usd) <= ZERO:
            raise ValueError("stake_usd must be > 0")
        require_decimal("profit_usd", self.profit_usd)


def roi(positions: Sequence[PaperPosition]) -> Decimal | InsufficientData:
    """Total net profit / total stake."""
    if not positions:
        return InsufficientData(("no positions to evaluate",))
    return sum((p.profit_usd for p in positions), ZERO) / sum(
        (p.stake_usd for p in positions), ZERO
    )


def sample_size_warnings(n: int, minimum: int = MIN_EVALUATION_SAMPLE) -> tuple[str, ...]:
    if n < minimum:
        return (f"sample size {n} is below the minimum {minimum}; metrics are not reliable",)
    return ()


@dataclass(frozen=True)
class CalibrationBin:
    lower: Decimal
    upper: Decimal  # exclusive, except the final bin which includes 1
    count: int
    mean_predicted: Decimal | None  # None when the bin is empty
    observed_frequency: Decimal | None  # None when suppressed (count < min_bin_sample)
    suppressed: bool


def calibration_bins(
    preds: Sequence[Prediction], n_bins: int = 10, min_bin_sample: int = MIN_BIN_SAMPLE
) -> tuple[CalibrationBin, ...]:
    if n_bins < 1 or min_bin_sample < 1:
        raise ValueError("n_bins and min_bin_sample must be >= 1")
    width = ONE / n_bins
    groups: list[list[Prediction]] = [[] for _ in range(n_bins)]
    for p in preds:
        groups[min(int(p.probability / width), n_bins - 1)].append(p)
    out: list[CalibrationBin] = []
    for i, g in enumerate(groups):
        n = len(g)
        suppressed = n < min_bin_sample
        out.append(
            CalibrationBin(
                lower=width * i,
                upper=width * (i + 1),
                count=n,
                mean_predicted=sum((p.probability for p in g), ZERO) / n if n else None,
                observed_frequency=None if suppressed else Decimal(sum(p.outcome for p in g)) / n,
                suppressed=suppressed,
            )
        )
    return tuple(out)


@dataclass(frozen=True)
class BaselineComparison:
    sample_size: int
    model_brier: Decimal
    baseline_brier: Decimal
    brier_skill: Decimal | None  # 1 - model/baseline; None if baseline is perfect
    beats_baseline: bool | None  # None = suppressed for small sample
    warnings: tuple[str, ...]


def compare_to_baseline(
    model: Sequence[Prediction],
    baseline: Sequence[Prediction],
    minimum: int = MIN_EVALUATION_SAMPLE,
) -> BaselineComparison | InsufficientData:
    """Brier comparison on the same events; ``baseline[i]`` must score the same outcome."""
    if len(model) != len(baseline):
        raise ValueError("model and baseline must cover the same events")
    if any(m.outcome != b.outcome for m, b in zip(model, baseline, strict=True)):
        raise ValueError("model and baseline outcomes differ")
    mb, bb = brier_score(model), brier_score(baseline)
    if isinstance(mb, InsufficientData):
        return mb
    if isinstance(bb, InsufficientData):
        return bb
    warnings = sample_size_warnings(len(model), minimum)
    return BaselineComparison(
        sample_size=len(model),
        model_brier=mb,
        baseline_brier=bb,
        brier_skill=None if bb == 0 else ONE - mb / bb,
        beats_baseline=None if warnings else mb < bb,
        warnings=warnings,
    )


@dataclass(frozen=True)
class EvaluationArtifact:
    """Versioned record of one out-of-sample evaluation; the only basis for activating a model."""

    artifact_id: str
    model_version: str
    code_version: str
    dataset_ref: str  # identifies the held-out data; must not overlap training data
    evaluated_at_utc: datetime
    comparison: BaselineComparison
    baseline_name: str
    log_loss: Decimal
    calibration: tuple[CalibrationBin, ...]

    def __post_init__(self) -> None:
        required = ("artifact_id", "model_version", "code_version", "dataset_ref", "baseline_name")
        for name in required:
            if not getattr(self, name):
                raise ValueError(f"{name} is required")
        require_aware("evaluated_at_utc", self.evaluated_at_utc)
        require_decimal("log_loss", self.log_loss)

    @property
    def supports_activation(self) -> bool:
        return self.comparison.beats_baseline is True and not self.comparison.warnings
