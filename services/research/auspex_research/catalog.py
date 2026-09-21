"""Provider-neutral event catalog model and deterministic resolution of a pasted event.

Resolution is exact-after-normalization only: no fuzzy or substring matching, so a query never
silently picks one of several plausible games. Zero matches and multiple matches are explicit
results, never guesses.
"""

import re
import unicodedata
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from enum import StrEnum

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from auspex_contracts import MarketType


class _Frozen(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def normalize_name(value: str) -> str:
    """Casefold, strip accents and punctuation, collapse whitespace. Deterministic."""
    folded = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    return " ".join(re.sub(r"[^a-z0-9]+", " ", folded.casefold()).split())


class CatalogTeam(_Frozen):
    name: str
    abbreviation: str | None = None
    alias: str | None = None
    safe_name: str | None = None
    provider_team_id: str | None = None

    @property
    def identifiers(self) -> frozenset[str]:
        raw = (self.name, self.abbreviation, self.alias, self.safe_name)
        return frozenset(n for v in raw if v and (n := normalize_name(v)))


class CatalogMarketRef(_Frozen):
    market_id: str
    slug: str | None
    market_type: MarketType | None  # None until settlement semantics for the type are confirmed
    provider_market_type: str | None


class CatalogEvent(_Frozen):
    provider: str
    event_id: str
    slug: str | None
    title: str | None
    start_utc: AwareDatetime | None  # the provider's game start; never guessed from other dates
    league_slug: str | None
    sport_slug: str | None
    teams: tuple[CatalogTeam, ...]
    markets: tuple[CatalogMarketRef, ...]
    is_open: bool
    live: bool | None
    ended: bool | None
    description: str | None  # provider text, verbatim
    resolution_source: str | None  # provider text, verbatim; not interpreted
    source_url: str
    retrieved_at: AwareDatetime
    warnings: tuple[str, ...] = ()

    @field_validator("start_utc", "retrieved_at")
    @classmethod
    def _to_utc(cls, value: datetime | None) -> datetime | None:
        return value.astimezone(UTC) if value is not None else None


class CatalogPage(_Frozen):
    """One page of catalog results. Rows that failed validation are named, never silently lost."""

    events: tuple[CatalogEvent, ...]
    skipped: tuple[str, ...] = ()
    offset: int = 0
    limit: int = 0


class EventQuery(_Frozen):
    """What a user pasted, already parsed: 1-2 participants and an optional start time."""

    participants: tuple[str, ...] = Field(min_length=1, max_length=2)
    start_utc: AwareDatetime | None = None
    window: timedelta = timedelta(hours=12)  # allowed |event start - query start|

    @model_validator(mode="after")
    def _non_blank(self) -> "EventQuery":
        if any(not normalize_name(p) for p in self.participants):
            raise ValueError("participant names must not be blank")
        return self


class ResolutionStatus(StrEnum):
    MATCHED = "MATCHED"
    AMBIGUOUS = "AMBIGUOUS"
    NO_MATCH = "NO_MATCH"


class EventResolution(_Frozen):
    status: ResolutionStatus
    matches: tuple[CatalogEvent, ...]  # 1 for MATCHED, 2+ for AMBIGUOUS, sorted (start, id)
    reason: str


def _matches(event: CatalogEvent, query: EventQuery) -> bool:
    remaining = [t.identifiers for t in event.teams]
    for participant in query.participants:  # each participant needs its own distinct team
        wanted = normalize_name(participant)
        hit = next((i for i, ids in enumerate(remaining) if wanted in ids), None)
        if hit is None:
            return False
        del remaining[hit]
    return True


def resolve_event(events: Sequence[CatalogEvent], query: EventQuery) -> EventResolution:
    by_team = [e for e in events if _matches(e, query)]
    unverifiable = 0
    if query.start_utc is not None:
        kept = [
            e
            for e in by_team
            if e.start_utc is not None and abs(e.start_utc - query.start_utc) <= query.window
        ]
        unverifiable = sum(e.start_utc is None for e in by_team)
        by_team = kept
    found = tuple(
        sorted(by_team, key=lambda e: (e.start_utc or datetime.max.replace(tzinfo=UTC), e.event_id))
    )
    note = (
        f"; {unverifiable} candidate(s) had no start time and were excluded" if unverifiable else ""
    )
    if not found:
        return EventResolution(
            status=ResolutionStatus.NO_MATCH, matches=(), reason="no catalog event matches" + note
        )
    if len(found) == 1:
        return EventResolution(
            status=ResolutionStatus.MATCHED, matches=found, reason="one exact match" + note
        )
    return EventResolution(
        status=ResolutionStatus.AMBIGUOUS,
        matches=found,
        reason=f"{len(found)} catalog events match; user must choose" + note,
    )
