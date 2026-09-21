"""Typed provider boundaries. Domain code depends on these, never on a concrete vendor."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, Protocol

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, ValidationError, field_validator

from auspex_contracts import MarketType, Side, Sport
from auspex_research.errors import ProviderError, ProviderErrorKind
from auspex_research.evidence import (
    EvidenceCategory,
    EvidenceItem,
    EvidenceSnapshot,
    ProviderFailure,
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
    """Cache keyed by request URL. Implementations must return what was stored, unmodified."""

    async def get(self, key: str) -> ProviderResponse[Any] | None: ...
    async def set(self, key: str, response: ProviderResponse[Any]) -> None: ...


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


def build_snapshot(
    event_id: str,
    results: Sequence[ProviderResponse[tuple[EvidenceItem, ...]] | ProviderError],
    created_at: datetime,
) -> EvidenceSnapshot:
    """Combine provider results into one snapshot; failures are recorded, never dropped."""
    items: dict[str, EvidenceItem] = {}
    failures = []
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
        else:
            items.update((i.evidence_id, i) for i in result.data)  # identical reports collapse
    return EvidenceSnapshot(
        event_id=event_id,
        created_at=created_at,
        items=tuple(items.values()),
        failures=tuple(failures),
    )
