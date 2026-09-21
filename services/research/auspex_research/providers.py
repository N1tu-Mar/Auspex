"""Typed provider boundaries. Domain code depends on these, never on a concrete vendor."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

from auspex_contracts import MarketType, Side, Sport
from auspex_research.catalog import CatalogEvent, CatalogPage, normalize_name
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.evidence import (
    ClaimKind,
    EvidenceCategory,
    EvidenceItem,
    EvidenceSnapshot,
    ProviderFailure,
    SourceRun,
)


@dataclass(frozen=True)
class SourceIdentity:
    provider: str  # stable adapter id, e.g. "polymarket_us"
    publisher: str  # human-readable owner of the data
    base_url: str  # fixed per provider; request paths never come from user input


@dataclass(frozen=True)
class CachePolicy:
    ttl_seconds: float  # 0 disables caching

    def is_fresh(self, retrieved_at: datetime, now: datetime) -> bool:
        return now - retrieved_at < timedelta(seconds=self.ttl_seconds)


@dataclass(frozen=True)
class ProviderResponse[T]:
    source: SourceIdentity
    url: str
    retrieved_at: datetime  # UTC, when the response arrived
    data: T
    attempts: int = 1
    from_cache: bool = False


class ResponseCache(Protocol):
    """Explicit-TTL cache. `get` returns None once an entry has expired: never stale data."""

    async def get(self, key: str) -> ProviderResponse[Any] | None: ...
    async def set(self, key: str, response: ProviderResponse[Any], ttl_seconds: float) -> None: ...


def validate_payload[M: BaseModel](model: type[M], data: Any, provider: str) -> M:
    """Schema-validate a provider payload, turning validation errors into ProviderError."""
    try:
        return model.model_validate(data)
    except ValidationError as exc:
        fields = sorted({".".join(map(str, e["loc"])) for e in exc.errors()})[:5]
        raise ProviderError(
            ProviderErrorKind.SCHEMA, provider, f"response failed validation at {fields}"
        ) from exc


class EventRef(BaseModel):
    """What a provider needs to look up evidence for one event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    sport: Sport
    league: str = Field(min_length=1)
    event_start_utc: AwareDatetime
    home_participant: str | None = None
    away_participant: str | None = None

    @field_validator("event_start_utc")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class MarketSideQuote(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    side_id: str
    description: str | None
    is_long: bool | None
    price_usd: Decimal | None = Field(gt=0, lt=1, description="Per-share price; None if unusable.")
    tradable: bool | None


class NormalizedMarket(BaseModel):
    """Provider-neutral view of one prediction market. Unknowns stay None and add a warning."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    market_id: str
    slug: str | None
    title: str | None
    market_type: MarketType | None
    provider_market_type: str | None
    line: Decimal | None
    event_start_utc: AwareDatetime | None
    is_open: bool
    combo_enabled: bool | None
    best_bid_usd: Decimal | None
    best_ask_usd: Decimal | None
    fee_coefficient: Decimal | None
    sides: tuple[MarketSideQuote, ...]
    source_url: str
    retrieved_at: AwareDatetime
    warnings: tuple[str, ...] = ()
    # Provider text, verbatim. Retrieved so a human or later stage can read the rules; never
    # parsed or interpreted here (settlement semantics are not inferred).
    description: str | None = None
    rules_disclaimer: str | None = None


class MarketSettlement(BaseModel):
    """Upstream-reported settlement value for a settled market. Semantics are not interpreted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str
    slug: str
    settlement_value: Decimal
    source_url: str
    retrieved_at: AwareDatetime


class PolymarketProvider(Protocol):
    source: SourceIdentity
    cache_policy: CachePolicy

    async def get_market_by_slug(self, slug: str) -> ProviderResponse[NormalizedMarket]: ...
    async def get_market_by_id(self, market_id: str) -> ProviderResponse[NormalizedMarket]: ...
    async def get_market_settlement(self, slug: str) -> ProviderResponse[MarketSettlement]: ...
    async def get_event_by_slug(self, slug: str) -> ProviderResponse[CatalogEvent]: ...
    async def list_events(
        self,
        *,
        start_after: datetime,
        start_before: datetime,
        tag_slug: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> ProviderResponse[CatalogPage]: ...


class OddsObservation(BaseModel):
    """One sportsbook price at one moment. De-vigging happens in the prediction stream."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1)
    book: str = Field(min_length=1)
    market_type: MarketType
    side: Side
    line: Decimal | None = None
    decimal_price: Decimal = Field(gt=1, description="Decimal odds, stake included in return.")
    observed_at: AwareDatetime

    @field_validator("observed_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class OddsProvider(Protocol):
    source: SourceIdentity
    cache_policy: CachePolicy

    async def get_odds(self, event: EventRef) -> ProviderResponse[tuple[OddsObservation, ...]]: ...


class EvidenceProvider(Protocol):
    """Shared shape for providers whose output is classified evidence."""

    source: SourceIdentity
    cache_policy: CachePolicy

    @property
    def category(self) -> EvidenceCategory: ...

    async def fetch_evidence(
        self, event: EventRef
    ) -> ProviderResponse[tuple[EvidenceItem, ...]]: ...


class StatsProvider(EvidenceProvider, Protocol):
    @property
    def category(self) -> Literal[EvidenceCategory.STATS]: ...


class NewsProvider(EvidenceProvider, Protocol):
    @property
    def category(self) -> Literal[EvidenceCategory.NEWS]: ...


class WeatherProvider(EvidenceProvider, Protocol):
    @property
    def category(self) -> Literal[EvidenceCategory.WEATHER]: ...


class InjuryProvider(EvidenceProvider, Protocol):
    @property
    def category(self) -> Literal[EvidenceCategory.INJURY]: ...


class LineupProvider(EvidenceProvider, Protocol):
    @property
    def category(self) -> Literal[EvidenceCategory.LINEUP]: ...


def _age_anchor(item: EvidenceItem) -> datetime:
    return item.source.published_at or item.source.retrieved_at


def build_snapshot(
    event_id: str,
    results: Sequence[ProviderResponse[tuple[EvidenceItem, ...]] | ProviderError],
    created_at: datetime,
    *,
    max_age: Mapping[EvidenceCategory, timedelta],
) -> EvidenceSnapshot:
    """Combine provider results into one immutable snapshot.

    - Failures are recorded, never dropped; each success is kept as a `SourceRun`.
    - Freshness is explicit: `max_age` must cover every category present. Older evidence (by
      publication time, else retrieval time) is dropped and recorded as a STALE failure.
    - Duplicates (same category, claim kind, and normalized fact) collapse to the earliest report;
      inferences that cited a collapsed item are re-pointed at the survivor.
    """
    failures: list[ProviderFailure] = []
    runs: list[SourceRun] = []
    fresh: list[EvidenceItem] = []
    stale: dict[tuple[str, EvidenceCategory], int] = {}
    for result in results:
        if isinstance(result, ProviderError):
            failures.append(
                ProviderFailure(
                    provider=result.provider,
                    kind=result.kind,
                    message=result.message,
                    occurred_at=created_at,
                )
            )
            continue
        runs.append(
            SourceRun(
                provider=result.source.provider,
                url=result.url,
                retrieved_at=result.retrieved_at,
                from_cache=result.from_cache,
                attempts=result.attempts,
                item_count=len(result.data),
            )
        )
        for item in result.data:
            if item.category not in max_age:
                raise ValueError(f"no freshness window for {item.category}")
            if created_at - _age_anchor(item) > max_age[item.category]:
                key = (item.source.provider, item.category)
                stale[key] = stale.get(key, 0) + 1
            else:
                fresh.append(item)
    for (provider, category), count in sorted(stale.items()):
        failures.append(
            ProviderFailure(
                provider=provider,
                kind=ProviderErrorKind.STALE,
                message=f"{count} {category} item(s) older than {max_age[category]} dropped",
                occurred_at=created_at,
            )
        )
    return EvidenceSnapshot(
        event_id=event_id,
        created_at=created_at,
        items=_dedupe(fresh),
        failures=tuple(failures),
        runs=tuple(runs),
    )


def _dedupe(items: Sequence[EvidenceItem]) -> tuple[EvidenceItem, ...]:
    survivors: dict[tuple[str, str, str], EvidenceItem] = {}
    for item in sorted(items, key=lambda i: (_age_anchor(i), i.evidence_id)):
        if item.claim_kind is not ClaimKind.INFERENCE:
            key = (item.category, item.claim_kind, normalize_name(item.extracted_fact))
            survivors.setdefault(key, item)
    keep = {i.evidence_id: i for i in survivors.values()}
    remap = {
        i.evidence_id: survivors[
            (i.category, i.claim_kind, normalize_name(i.extracted_fact))
        ].evidence_id
        for i in items
        if i.claim_kind is not ClaimKind.INFERENCE
    }
    for item in items:  # inferences in input order; a citation of a later inference stays as is
        if item.claim_kind is ClaimKind.INFERENCE:
            cited = tuple(dict.fromkeys(remap.get(d, d) for d in item.derived_from))
            fixed = item.model_copy(update={"derived_from": cited, "evidence_id": ""})
            fixed = EvidenceItem.model_validate(fixed.model_dump())
            remap[item.evidence_id] = fixed.evidence_id
            keep[fixed.evidence_id] = fixed
    return tuple(keep.values())
