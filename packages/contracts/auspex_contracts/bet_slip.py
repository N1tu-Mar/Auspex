from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated

from pydantic import AwareDatetime, Field, field_validator

from auspex_contracts._base import Contract as _Contract


class Sport(StrEnum):
    NFL = "NFL"
    NCAAF = "NCAAF"
    MLB = "MLB"
    SOCCER = "SOCCER"


class MarketType(StrEnum):
    MONEYLINE = "MONEYLINE"
    SPREAD = "SPREAD"
    TOTAL = "TOTAL"
    PLAYER_PROP = "PLAYER_PROP"


class Side(StrEnum):
    HOME = "HOME"
    AWAY = "AWAY"
    DRAW = "DRAW"
    OVER = "OVER"
    UNDER = "UNDER"
    YES = "YES"
    NO = "NO"


class LegStatus(StrEnum):
    PREGAME = "PREGAME"
    LIVE = "LIVE"
    COMPLETED = "COMPLETED"
    POSTPONED = "POSTPONED"
    CANCELED = "CANCELED"
    UNSUPPORTED = "UNSUPPORTED"


class Recommendation(StrEnum):
    CONSIDER = "CONSIDER"
    PASS = "PASS"  # noqa: S105 - recommendation state, not a secret
    AVOID = "AVOID"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Polymarket share price in USD; a binary share pays 1.00 USD, so price lies strictly in (0, 1).
MarketPriceUsd = Annotated[Decimal, Field(gt=0, lt=1, max_digits=6, decimal_places=4)]
PositiveUsd = Annotated[Decimal, Field(gt=0, max_digits=12, decimal_places=2)]


class BetLeg(_Contract):
    sport: Sport
    league: str = Field(min_length=1)
    event_id: str | None = None
    event_start_utc: AwareDatetime = Field(
        description="Event start; any offset accepted, stored and returned as UTC."
    )
    home_participant: str | None = None
    away_participant: str | None = None
    player_id: str | None = None
    market_type: MarketType
    side: Side
    line: Decimal | None = Field(default=None, description="Spread or total threshold.")
    polymarket_market_id: str | None = None
    market_price_usd: MarketPriceUsd
    settlement_rule_ref: str | None = None
    status: LegStatus = LegStatus.PREGAME

    @field_validator("event_start_utc")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class BetSlip(_Contract):
    original_input: str | None = Field(
        default=None, description="Verbatim user submission, kept for audit."
    )
    legs: list[BetLeg] = Field(min_length=1)
    stake_usd: PositiveUsd
    gross_payout_usd: PositiveUsd | None = Field(
        default=None,
        description="Quoted payout including returned stake; semantics confirmed per market.",
    )
