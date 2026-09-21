"""Combo (parlay) probability baseline and settlement states."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from auspex_contracts import BetLeg
from auspex_prediction.core import ONE, InsufficientData, pregame_blockers, require_probability
from auspex_prediction.correlation import CorrelationWarning, detect_correlation_warnings


@dataclass(frozen=True)
class NaiveIndependentBaseline:
    """Product of leg probabilities. A comparison baseline only, never a recommendation input."""

    probability: Decimal
    label: str = "NAIVE_INDEPENDENT_BASELINE"
    assumption: str = "treats legs as independent; wrong whenever legs share a dependency"


@dataclass(frozen=True)
class ComboAssessment:
    naive_baseline: NaiveIndependentBaseline
    warnings: tuple[CorrelationWarning, ...]
    # Correlation-aware joint probability. Always INSUFFICIENT_DATA until a validated
    # correlation model exists; warnings list what such a model would need to handle.
    joint_probability: InsufficientData


def naive_independent_probability(leg_probabilities: Sequence[Decimal]) -> NaiveIndependentBaseline:
    if len(leg_probabilities) < 2:
        raise ValueError("a combo needs at least two legs")
    product = ONE
    for i, p in enumerate(leg_probabilities):
        product *= require_probability(f"leg_probabilities[{i}]", p)
    return NaiveIndependentBaseline(product)


def assess_combo(
    legs: list[BetLeg], leg_probabilities: Sequence[Decimal], *, as_of_utc: datetime
) -> ComboAssessment | InsufficientData:
    """Pregame combo assessment: labeled baseline, dependency warnings, joint probability.

    Returns INSUFFICIENT_DATA outright when any leg is not pregame-priceable.
    """
    if len(legs) != len(leg_probabilities):
        raise ValueError("legs and leg_probabilities must have equal length")
    blockers = [
        f"leg {i}: {r}" for i, leg in enumerate(legs) for r in pregame_blockers(leg, as_of_utc)
    ]
    if blockers:
        return InsufficientData(tuple(blockers))
    warnings = tuple(detect_correlation_warnings(legs))
    reason = (
        f"{len(warnings)} shared-dependency warning(s); no validated correlation model"
        if warnings
        else "no shared dependency detected, but no validated correlation model confirms "
        "independence"
    )
    return ComboAssessment(
        naive_baseline=naive_independent_probability(leg_probabilities),
        warnings=warnings,
        joint_probability=InsufficientData((reason,)),
    )


class LegResult(StrEnum):
    WON = "WON"
    LOST = "LOST"
    VOID = "VOID"
    UNRESOLVED = "UNRESOLVED"  # pending, postponed, suspended, or awaiting official result


class VoidPolicy(StrEnum):
    """How the venue's combo rules treat a void leg. Must come from settlement rules."""

    REMOVE_VOID_LEGS = "REMOVE_VOID_LEGS"  # combo reprices over remaining legs
    VOID_ENTIRE_COMBO = "VOID_ENTIRE_COMBO"


class ComboSettlement(StrEnum):
    WON = "WON"
    LOST = "LOST"
    VOID = "VOID"  # stake returned
    WON_REPRICED = "WON_REPRICED"  # won on remaining legs; payout must be recomputed
    UNRESOLVED = "UNRESOLVED"
    RULE_UNKNOWN = "RULE_UNKNOWN"  # a void leg exists and no void policy was confirmed


def settle_combo(results: Sequence[LegResult], void_policy: VoidPolicy | None) -> ComboSettlement:
    """Deterministic combo state from leg results. ``void_policy=None`` means unconfirmed.

    Any lost leg loses the combo. Otherwise any unresolved leg keeps it unresolved; postponed
    legs are UNRESOLVED, never assumed void.
    """
    if len(results) < 2:
        raise ValueError("a combo needs at least two legs")
    if LegResult.LOST in results:
        return ComboSettlement.LOST
    if LegResult.UNRESOLVED in results:
        return ComboSettlement.UNRESOLVED
    if LegResult.VOID not in results:
        return ComboSettlement.WON
    if void_policy is None:
        return ComboSettlement.RULE_UNKNOWN
    if void_policy is VoidPolicy.VOID_ENTIRE_COMBO or all(r is LegResult.VOID for r in results):
        return ComboSettlement.VOID
    return ComboSettlement.WON_REPRICED
