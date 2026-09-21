"""Shared input guards and the explicit INSUFFICIENT_DATA outcome.

Two failure channels, never mixed:
- Malformed input (wrong type, out-of-bounds value) raises ``TypeError``/``ValueError``.
- Well-formed input that cannot support a responsible estimate returns ``InsufficientData``.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from auspex_contracts import BetLeg, LegStatus, Recommendation

ZERO = Decimal(0)
ONE = Decimal(1)
HUNDRED = Decimal(100)


@dataclass(frozen=True)
class InsufficientData:
    """No responsible estimate is possible; ``reasons`` says why, in plain language."""

    reasons: tuple[str, ...]
    status: Recommendation = Recommendation.INSUFFICIENT_DATA

    def __post_init__(self) -> None:
        if not self.reasons:
            raise ValueError("InsufficientData requires at least one reason")


def require_decimal(name: str, value: object) -> Decimal:
    """Accept only finite ``Decimal``. Floats are rejected so money never touches binary floats."""
    if not isinstance(value, Decimal):
        raise TypeError(f"{name} must be Decimal, got {type(value).__name__}")
    if not value.is_finite():
        raise ValueError(f"{name} must be finite, got {value}")
    return value


def require_probability(name: str, value: object, *, open_interval: bool = False) -> Decimal:
    """Probability in [0, 1], or (0, 1) when ``open_interval``."""
    p = require_decimal(name, value)
    if open_interval and not ZERO < p < ONE:
        raise ValueError(f"{name} must be in (0, 1), got {p}")
    if not ZERO <= p <= ONE:
        raise ValueError(f"{name} must be in [0, 1], got {p}")
    return p


def require_usd(name: str, value: object, *, positive: bool = False) -> Decimal:
    usd = require_decimal(name, value)
    if positive and usd <= ZERO:
        raise ValueError(f"{name} must be > 0, got {usd}")
    if usd < ZERO:
        raise ValueError(f"{name} must be >= 0, got {usd}")
    return usd


def require_aware(name: str, value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be timezone-aware")
    return value


def pregame_blockers(leg: BetLeg, as_of_utc: datetime) -> list[str]:
    """Reasons a leg cannot receive a pregame estimate at ``as_of_utc``; empty means none.

    Postponed, canceled, live, completed, and unsupported legs are never priced here: their
    outcome depends on market-specific settlement rules (void, regrade, or carry-over) that the
    caller must resolve first.
    """
    require_aware("as_of_utc", as_of_utc)
    if leg.status is not LegStatus.PREGAME:
        return [
            f"leg status {leg.status.value} is not PREGAME; settlement rule decides its outcome"
        ]
    if leg.event_start_utc <= as_of_utc:
        return ["event has started or start time has passed; pregame estimate not valid"]
    return []
