"""Read-only Polymarket US adapter (public market data, no auth, no trading).

Documented, public, unauthenticated GET endpoints only (docs.polymarket.us/api-reference, read
2026-09-21): market by slug and id, market settlement, event by slug, and the events list. Only
fields Auspex uses are validated; unknown upstream fields are ignored so additive API changes do
not break intake, while shape changes to used fields fail loudly.
"""

import re
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from auspex_contracts import MarketType
from auspex_research.catalog import CatalogEvent, CatalogMarketRef, CatalogPage, CatalogTeam
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.providers import (
    CachePolicy,
    MarketSettlement,
    MarketSideQuote,
    NormalizedMarket,
    ProviderResponse,
    SourceIdentity,
    validate_payload,
)
from auspex_research.transport import Fetcher, Param

POLYMARKET_US = SourceIdentity(
    provider="polymarket_us", publisher="Polymarket US", base_url="https://gateway.polymarket.us"
)
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,199}$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
MAX_PAGE = 100
TTL_MARKET_S = 15.0  # prices move; keep short
TTL_CATALOG_S = 300.0  # schedules change slowly
TTL_SETTLEMENT_S = 60.0
_MARKET_TYPES = {
    "MONEYLINE": MarketType.MONEYLINE,
    "SPREAD": MarketType.SPREAD,
    "TOTAL": MarketType.TOTAL,
    # PROP, FUTURE, DRAWABLE_OUTCOME: not mapped until their settlement semantics are confirmed.
}


class _Upstream(BaseModel):
    model_config = ConfigDict(
        extra="ignore", frozen=True, alias_generator=to_camel, coerce_numbers_to_str=True
    )


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
    sports_market_type: str | None = None  # older field on event-embedded markets
    description: str | None = None
    rules_disclaimer: str | None = None
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
    provider_type = _provider_type(market)
    market_type = _MARKET_TYPES.get(provider_type or "")
    if market_type is None:
        warnings.append(f"unsupported market type {provider_type!r}")
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
        provider_market_type=provider_type,
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
        description=market.description,
        rules_disclaimer=market.rules_disclaimer,
    )


def _provider_type(market: Market) -> str | None:
    """Prefer the V2 enum; fall back to the older field only when V2 is absent."""
    raw = market.sports_market_type_v2 or market.sports_market_type
    return raw.upper() if raw else None


class Settlement(_Upstream):
    slug: str
    settlement: Decimal


class League(_Upstream):
    slug: str | None = None


class SportRef(_Upstream):
    slug: str | None = None


class Tag(_Upstream):
    league: League | None = None
    sport: SportRef | None = None


class EventMarket(Market):
    tags: tuple[Tag, ...] = ()


class Team(_Upstream):
    id: str | None = None
    name: str
    abbreviation: str | None = None
    alias: str | None = None
    safe_name: str | None = None


class Event(_Upstream):
    id: str
    slug: str | None = None
    title: str | None = None
    description: str | None = None
    resolution_source: str | None = None
    start_time: datetime | None = None
    active: bool | None = None
    closed: bool | None = None
    archived: bool | None = None
    live: bool | None = None
    ended: bool | None = None
    markets: tuple[EventMarket, ...] = ()
    teams: tuple[Team, ...] = ()


class EventEnvelope(_Upstream):
    event: Event


class EventsEnvelope(_Upstream):
    events: tuple[Any, ...]  # each row validated on its own so one bad row is not fatal


def _single_slug(values: set[str], label: str, warnings: list[str]) -> str | None:
    if len(values) == 1:
        return next(iter(values))
    warnings.append(f"{label} missing" if not values else f"{label} disagrees across markets")
    return None


def normalize_event(event: Event, source_url: str, retrieved_at: datetime) -> CatalogEvent:
    """Pure, deterministic mapping. Unknowns stay None with a warning; nothing is guessed."""
    warnings: list[str] = []
    start = event.start_time
    if start is not None and start.tzinfo is None:
        warnings.append("startTime has no timezone; ignored")
        start = None
    elif start is None:
        warnings.append("startTime missing")  # startDate/eventDate are not a game start
    tags = [t for m in event.markets for t in m.tags]
    league = _single_slug(
        {t.league.slug for t in tags if t.league and t.league.slug}, "league", warnings
    )
    sport = _single_slug(
        {t.sport.slug for t in tags if t.sport and t.sport.slug}, "sport", warnings
    )
    if not event.teams:
        warnings.append("event has no teams")
    refs = []
    for m in event.markets:
        provider_type = _provider_type(m)
        refs.append(
            CatalogMarketRef(
                market_id=m.id,
                slug=m.slug,
                market_type=_MARKET_TYPES.get(provider_type or ""),
                provider_market_type=provider_type,
            )
        )
    return CatalogEvent(
        provider=POLYMARKET_US.provider,
        event_id=event.id,
        slug=event.slug,
        title=event.title,
        start_utc=start.astimezone(UTC) if start else None,
        league_slug=league,
        sport_slug=sport,
        teams=tuple(
            CatalogTeam(
                name=t.name,
                abbreviation=t.abbreviation,
                alias=t.alias,
                safe_name=t.safe_name,
                provider_team_id=t.id,
            )
            for t in event.teams
        ),
        markets=tuple(refs),
        is_open=event.active is True and event.closed is not True and event.archived is not True,
        live=event.live,
        ended=event.ended,
        description=event.description,
        resolution_source=event.resolution_source,
        source_url=source_url,
        retrieved_at=retrieved_at,
        warnings=tuple(warnings),
    )


def _iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        raise ValueError("datetime must be timezone-aware")
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class PolymarketUSClient:
    """Implements PolymarketProvider over any Transport (live client or FixtureTransport)."""

    source = POLYMARKET_US
    cache_policy = CachePolicy(ttl_seconds=TTL_MARKET_S)

    def __init__(self, fetcher: Fetcher) -> None:
        self._fetcher = fetcher

    def _bad(self, what: str) -> ProviderError:
        # Reject before any request: identifiers are interpolated into the URL path.
        return ProviderError(ProviderErrorKind.BAD_REQUEST, self.source.provider, f"invalid {what}")

    async def _get(
        self, path: str, ttl: float, params: dict[str, Param] | None = None
    ) -> ProviderResponse[Any]:
        return await self._fetcher.get(self.source, path, params, ttl_seconds=ttl)

    async def _market(self, path: str) -> ProviderResponse[NormalizedMarket]:
        response = await self._get(path, TTL_MARKET_S)
        envelope = validate_payload(MarketEnvelope, response.data, self.source.provider)
        normalized = normalize_market(envelope.market, response.url, response.retrieved_at)
        return replace(response, data=normalized)

    async def get_market_by_slug(self, slug: str) -> ProviderResponse[NormalizedMarket]:
        if not _SLUG.fullmatch(slug):
            raise self._bad("slug")
        return await self._market(f"/v1/market/slug/{slug}")

    async def get_market_by_id(self, market_id: str) -> ProviderResponse[NormalizedMarket]:
        if not _ID.fullmatch(market_id):
            raise self._bad("market id")
        return await self._market(f"/v1/market/id/{market_id}")

    async def get_market_settlement(self, slug: str) -> ProviderResponse[MarketSettlement]:
        """Upstream 404 means "not found or not settled"; it is not treated as either."""
        if not _SLUG.fullmatch(slug):
            raise self._bad("slug")
        try:
            response = await self._get(f"/v1/markets/{slug}/settlement", TTL_SETTLEMENT_S)
        except ProviderError as exc:
            if exc.kind is ProviderErrorKind.NOT_FOUND:
                raise ProviderError(
                    exc.kind,
                    exc.provider,
                    "market not found or not settled (upstream does not say)",
                    status_code=exc.status_code,
                    attempts=exc.attempts,
                ) from exc
            raise
        parsed = validate_payload(Settlement, response.data, self.source.provider)
        if parsed.slug != slug:
            raise ProviderError(ProviderErrorKind.SCHEMA, self.source.provider, "slug mismatch")
        return replace(
            response,
            data=MarketSettlement(
                provider=self.source.provider,
                slug=parsed.slug,
                settlement_value=parsed.settlement,
                source_url=response.url,
                retrieved_at=response.retrieved_at,
            ),
        )

    async def get_event_by_slug(self, slug: str) -> ProviderResponse[CatalogEvent]:
        if not _SLUG.fullmatch(slug):
            raise self._bad("slug")
        response = await self._get(f"/v1/events/slug/{slug}", TTL_CATALOG_S)
        envelope = validate_payload(EventEnvelope, response.data, self.source.provider)
        return replace(
            response, data=normalize_event(envelope.event, response.url, response.retrieved_at)
        )

    async def list_events(
        self,
        *,
        start_after: datetime,
        start_before: datetime,
        tag_slug: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProviderResponse[CatalogPage]:
        """One bounded page of open events starting in a window; callers page with `offset`."""
        if not (1 <= limit <= MAX_PAGE and offset >= 0):
            raise self._bad("page bounds")
        if tag_slug is not None and not _SLUG.fullmatch(tag_slug):
            raise self._bad("tag slug")
        params: dict[str, Param] = {
            "startTimeMin": _iso_utc(start_after),
            "startTimeMax": _iso_utc(start_before),
            "active": True,
            "closed": False,
            "limit": limit,
            "offset": offset,
        }
        if tag_slug:
            params["tagSlug"] = tag_slug
        response = await self._get("/v1/events", TTL_CATALOG_S, params)
        rows = validate_payload(EventsEnvelope, response.data, self.source.provider).events
        events: list[CatalogEvent] = []
        skipped: list[str] = []
        for index, row in enumerate(rows):
            try:
                event = validate_payload(Event, row, self.source.provider)
            except ProviderError as exc:
                skipped.append(f"events[{index}]: {exc.message}")
                continue
            events.append(normalize_event(event, response.url, response.retrieved_at))
        page = CatalogPage(events=tuple(events), skipped=tuple(skipped), offset=offset, limit=limit)
        return replace(response, data=page)
