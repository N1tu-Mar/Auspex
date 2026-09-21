"""Transparent correlation warnings between combo legs.

This is a detection framework, not a correlation model. It names shared dependencies that make
the independence assumption unsafe; it never estimates their magnitude. Any warning means a
correlation-aware joint probability is not available (see ``combo.assess_combo``).
"""

from dataclasses import dataclass
from enum import StrEnum
from itertools import combinations

from auspex_contracts import BetLeg


class DependencyKind(StrEnum):
    SHARED_GAME = "SHARED_GAME"
    SAME_MARKET = "SAME_MARKET"  # same game and market type: nested or mutually exclusive
    SHARED_TEAM = "SHARED_TEAM"
    SHARED_PLAYER = "SHARED_PLAYER"
    SHARED_WEATHER = "SHARED_WEATHER"
    GAME_SCRIPT = "GAME_SCRIPT"
    UNKNOWN_DEPENDENCY = "UNKNOWN_DEPENDENCY"  # not enough identifiers to rule dependency out


@dataclass(frozen=True)
class CorrelationWarning:
    kind: DependencyKind
    leg_indices: tuple[int, ...]
    explanation: str
    magnitude: str = "UNQUANTIFIED"  # no validated correlation model exists yet


def _participants(leg: BetLeg) -> frozenset[str]:
    return frozenset(
        p.strip().casefold() for p in (leg.home_participant, leg.away_participant) if p
    )


def _identifiable(leg: BetLeg) -> bool:
    return leg.event_id is not None or len(_participants(leg)) == 2


def _same_game(a: BetLeg, b: BetLeg) -> bool:
    if a.event_id is not None and b.event_id is not None:
        return a.event_id == b.event_id
    return (
        a.sport == b.sport
        and a.league == b.league
        and a.event_start_utc == b.event_start_utc
        and len(_participants(a)) == 2
        and _participants(a) == _participants(b)
    )


def _pair_warnings(i: int, a: BetLeg, j: int, b: BetLeg) -> list[CorrelationWarning]:
    pair = (i, j)
    out: list[CorrelationWarning] = []

    def warn(kind: DependencyKind, why: str) -> None:
        out.append(CorrelationWarning(kind, pair, why))

    if a.player_id is not None and a.player_id == b.player_id:
        warn(DependencyKind.SHARED_PLAYER, f"both legs depend on player {a.player_id}")

    if _same_game(a, b):
        warn(DependencyKind.SHARED_GAME, "both legs settle on the same game")
        warn(
            DependencyKind.SHARED_WEATHER,
            "same game shares weather and venue conditions (roof status unknown)",
        )
        if a.market_type == b.market_type and a.player_id == b.player_id:
            warn(
                DependencyKind.SAME_MARKET,
                f"same game and market type {a.market_type.value}: legs may be nested or "
                "mutually exclusive",
            )
        else:
            warn(
                DependencyKind.GAME_SCRIPT,
                f"{a.market_type.value} and {b.market_type.value} outcomes both depend on how "
                "the game unfolds (score, pace, blowout risk)",
            )
    elif shared := sorted(_participants(a) & _participants(b)):
        warn(DependencyKind.SHARED_TEAM, f"different games share participant(s) {shared}")
    return out


def detect_correlation_warnings(legs: list[BetLeg]) -> list[CorrelationWarning]:
    """All detected pairwise shared dependencies, plus legs too under-identified to check."""
    out = [
        CorrelationWarning(
            DependencyKind.UNKNOWN_DEPENDENCY,
            (i,),
            "leg has no event_id or full participant pair; shared dependencies cannot be ruled out",
        )
        for i, leg in enumerate(legs)
        if not _identifiable(leg)
    ]
    for (i, a), (j, b) in combinations(enumerate(legs), 2):
        out.extend(_pair_warnings(i, a, j, b))
    return out
