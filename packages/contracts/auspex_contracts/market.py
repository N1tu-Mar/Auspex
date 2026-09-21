"""Normalized event and market identity, plus append-only snapshots of their mutable state.

Identity rows never change. Anything that can change (start time, status, prices, open/closed)
lives in a snapshot, so history is preserved by inserting a new snapshot, never by editing.
"""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from pydantic import AwareDatetime, Field, field_validator, model_validator

from auspex_contracts._base import Contract
from auspex_contracts.bet_slip import LegStatus, MarketPriceUsd, MarketType, Sport
from auspex_contracts.evidence import SourceSnapshot


class Event(Contract):
    """Canonical event identity. `event_id` is the id carried by `BetLeg.event_id`."""

    event_id: str = Field(min_length=1)
    sport: Sport
    league: str = Field(min_length=1)
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class EventSnapshot(Contract):
    id: UUID = Field(default_factory=uuid4)
    event_id: str = Field(min_length=1)
    captured_at: AwareDatetime
    event_start_utc: AwareDatetime
    status: LegStatus
    home_participant: str | None = None
    away_participant: str | None = None
    source: SourceSnapshot

    @field_validator("captured_at", "event_start_utc")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class Market(Contract):
    """Provider market identity. A different line is a different market."""

    provider: str = Field(min_length=1)
    market_id: str = Field(min_length=1)
    event_id: str = Field(min_length=1)
    market_type: MarketType | None = Field(
        default=None, description="None when the provider type has no normalized equivalent."
    )
    provider_market_type: str | None = None
    line: Decimal | None = None
    slug: str | None = None
    created_at: AwareDatetime

    @field_validator("created_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class MarketSideQuote(Contract):
    side_id: str
    description: str | None = None
    is_long: bool | None = None
    price_usd: MarketPriceUsd | None = Field(
        default=None, description="Per-share price in USD; None if unusable."
    )
    tradable: bool | None = None


class MarketSnapshot(Contract):
    """One observation of a market's tradable state. Unknowns stay None and add a warning."""

    id: UUID = Field(default_factory=uuid4)
    provider: str = Field(min_length=1)
    market_id: str = Field(min_length=1)
    captured_at: AwareDatetime
    title: str | None = None
    is_open: bool
    combo_enabled: bool | None = None
    best_bid_usd: MarketPriceUsd | None = None
    best_ask_usd: MarketPriceUsd | None = None
    fee_coefficient: Decimal | None = Field(default=None, ge=0)
    sides: tuple[MarketSideQuote, ...] = ()
    warnings: tuple[str, ...] = ()
    source: SourceSnapshot

    @field_validator("captured_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _bid_not_above_ask(self) -> "MarketSnapshot":
        if (
            self.best_bid_usd is not None
            and self.best_ask_usd is not None
            and self.best_bid_usd > self.best_ask_usd
        ):
            raise ValueError("best_bid_usd is above best_ask_usd")
        return self
