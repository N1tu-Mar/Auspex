"""Authoritative Auspex domain contracts.

These Pydantic models are the single source of truth for cross-language types.
TypeScript types are generated from the API OpenAPI schema; never hand-write them.
"""

from auspex_contracts.bet_slip import (
    BetLeg,
    BetSlip,
    LegStatus,
    MarketType,
    Recommendation,
    Side,
    Sport,
)

__all__ = [
    "BetLeg",
    "BetSlip",
    "LegStatus",
    "MarketType",
    "Recommendation",
    "Side",
    "Sport",
]
