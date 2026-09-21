"""Read-only Polymarket US adapter (public market data, no auth, no trading).

Schema follows https://docs.polymarket.us/api-reference/markets/get-market-by-slug (fetched
2026-09-21). Only fields Auspex uses are validated; unknown upstream fields are ignored so
additive API changes do not break intake, while shape changes to used fields fail loudly.
"""

import re
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from auspex_contracts import MarketType
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.providers import (
    CachePolicy,
    MarketSideQuote,
    NormalizedMarket,
    ProviderResponse,
    SourceIdentity,
    validate_payload,
)
from auspex_research.transport import RetryPolicy, Transport, fetch_json, utc_now

POLYMARKET_US = SourceIdentity(
    provider="polymarket_us", publisher="Polymarket US", base_url="https://gateway.polymarket.us"
)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")
_MARKET_TYPES = {
    "MONEYLINE": MarketType.MONEYLINE,
    "SPREAD": MarketType.SPREAD,
    "TOTAL": MarketType.TOTAL,
    # PROP, FUTURE, DRAWABLE_OUTCOME: not mapped until their settlement semantics are confirmed.
}


class _Upstream(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=True, alias_generator=to_camel)


class Quote(_Upstream):
    value: Decimal
    currency: str


class MarketSide(_Upstream):
    id: str
    description: str | None = None
    long: bool | None = None
    price: Decimal | None = None
    tradable: bool | None = None


class Market(_Upstream):
    id: str
    slug: str | None = None
    question: str | None = None
    title: str | None = None
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    game_start_time: datetime | None = None
    sports_market_type_v2: str | None = None
    line: Decimal | None = None
    market_sides: tuple[MarketSide, ...] = ()
    best_bid_quote: Quote | None = None
    best_ask_quote: Quote | None = None
    fee_coefficient: Decimal | None = None
    combo_enabled: bool | None = None


class MarketEnvelope(_Upstream):
    market: Market


def _usd_price(value: Decimal | None, label: str, warnings: list[str]) -> Decimal | None:
    if value is None:
        return None
    if 0 < value < 1:
        return value
    warnings.append(f"{label} {value} outside (0, 1); ignored")
    return None


def _quote_usd(quote: Quote | None, label: str, warnings: list[str]) -> Decimal | None:
    if quote is None:
        return None
    if quote.currency.upper() != "USD":
        warnings.append(f"{label} currency {quote.currency!r} is not USD; ignored")
        return None
    return _usd_price(quote.value, label, warnings)


def normalize_market(market: Market, source_url: str, retrieved_at: datetime) -> NormalizedMarket:
    """Pure, deterministic mapping from the upstream shape. Never guesses a missing value."""
    warnings: list[str] = []
    start = market.game_start_time
    if start is not None and start.tzinfo is None:
        warnings.append("gameStartTime has no timezone; ignored")
        start = None
    elif start is None:
        warnings.append("gameStartTime missing")
    market_type = _MARKET_TYPES.get(market.sports_market_type_v2 or "")
    if market_type is None:
        warnings.append(f"unsupported market type {market.sports_market_type_v2!r}")
    if not market.market_sides:
        warnings.append("market has no sides")
    sides = tuple(
        MarketSideQuote(
            side_id=side.id,
            description=side.description,
            is_long=side.long,
            price_usd=_usd_price(side.price, f"side {side.id} price", warnings),
            tradable=side.tradable,
        )
        for side in market.market_sides
    )
    return NormalizedMarket(
        provider=POLYMARKET_US.provider,
        market_id=market.id,
        slug=market.slug,
        title=market.title or market.question,
        market_type=market_type,
        provider_market_type=market.sports_market_type_v2,
        line=market.line,
        event_start_utc=start.astimezone(UTC) if start else None,
        is_open=market.active is True and market.closed is not True and market.archived is not True,
        combo_enabled=market.combo_enabled,
        best_bid_usd=_quote_usd(market.best_bid_quote, "best bid", warnings),
        best_ask_usd=_quote_usd(market.best_ask_quote, "best ask", warnings),
        fee_coefficient=market.fee_coefficient,
        sides=sides,
        source_url=source_url,
        retrieved_at=retrieved_at,
        warnings=tuple(warnings),
    )


class PolymarketUSClient:
    """Implements PolymarketProvider over any Transport (live client or FixtureTransport)."""

    source = POLYMARKET_US
    cache_policy = CachePolicy(ttl_seconds=15)  # prices move; keep short

    def __init__(
        self,
        transport: Transport,
        policy: RetryPolicy = RetryPolicy(),  # noqa: B008 - frozen, safe to share
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._transport = transport
        self._policy = policy
        self._clock = clock

    async def get_market_by_slug(self, slug: str) -> ProviderResponse[NormalizedMarket]:
        if not _SLUG.fullmatch(slug):
            # Reject before any request: slugs are interpolated into the URL path.
            raise ProviderError(ProviderErrorKind.BAD_REQUEST, self.source.provider, "invalid slug")
        response = await fetch_json(
            self._transport, self.source, f"/v1/market/slug/{slug}", self._policy, clock=self._clock
        )
        envelope = validate_payload(MarketEnvelope, response.data, self.source.provider)
        normalized = normalize_market(envelope.market, response.url, response.retrieved_at)
        return replace(response, data=normalized)
