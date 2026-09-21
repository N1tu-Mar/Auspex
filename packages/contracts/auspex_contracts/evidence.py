"""Immutable, content-addressed source and evidence snapshots.

Evidence ids and snapshot ids are SHA-256 hashes of their content, so a stored snapshot can be
re-validated later and any silent edit is detected. Nothing here stores full article bodies.
"""

import hashlib
from datetime import UTC, datetime
from enum import StrEnum
from typing import Self
from urllib.parse import urlsplit

from pydantic import AwareDatetime, BaseModel, Field, field_validator, model_validator

from auspex_contracts._base import Contract

MAX_EXCERPT_CHARS = 300  # short quotation only; store extracted facts, not copied pages


class ClaimKind(StrEnum):
    CONFIRMED_FACT = "CONFIRMED_FACT"  # official or on-record confirmation
    PROJECTION = "PROJECTION"  # expected but unconfirmed (projected lineup, forecast)
    RUMOR = "RUMOR"  # unattributed or unverified report
    OPINION = "OPINION"  # analyst or pundit view
    INFERENCE = "INFERENCE"  # derived from other evidence; must cite it via derived_from


class EvidenceCategory(StrEnum):
    MARKET = "MARKET"
    ODDS = "ODDS"
    STATS = "STATS"
    NEWS = "NEWS"
    WEATHER = "WEATHER"
    INJURY = "INJURY"
    LINEUP = "LINEUP"


class ProviderErrorKind(StrEnum):
    TIMEOUT = "TIMEOUT"
    RATE_LIMITED = "RATE_LIMITED"
    UNAVAILABLE = "UNAVAILABLE"  # network failure or 5xx
    NOT_FOUND = "NOT_FOUND"
    BAD_REQUEST = "BAD_REQUEST"  # other 4xx; our request is wrong or refused
    SCHEMA = "SCHEMA"  # response did not match the expected shape


def _utc(value: datetime | None) -> datetime | None:
    return value.astimezone(UTC) if value is not None else None


def _content_id(model: BaseModel, id_field: str) -> str:
    payload = model.model_dump_json(exclude={id_field})
    return hashlib.sha256(payload.encode()).hexdigest()


def _seal(model: BaseModel, id_field: str) -> None:
    """Fill an empty content id, or reject one that does not match the content."""
    expected = _content_id(model, id_field)
    current = getattr(model, id_field)
    if not current:
        object.__setattr__(model, id_field, expected)  # frozen model; set once during validation
    elif current != expected:
        raise ValueError(f"{id_field} does not match content")


class SourceSnapshot(Contract):
    """Where a fact, quote, or event state came from and when it was retrieved."""

    provider: str = Field(min_length=1, description="Adapter that retrieved it.")
    publisher: str = Field(min_length=1)
    url: str
    published_at: AwareDatetime | None = Field(default=None, description="When the source says.")
    retrieved_at: AwareDatetime
    content_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")

    @field_validator("url")
    @classmethod
    def _http_url(cls, value: str) -> str:
        parts = urlsplit(value)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError("source url must be an absolute http(s) URL")
        return value

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def _to_utc(cls, value: datetime | None) -> datetime | None:
        return _utc(value)

    @model_validator(mode="after")
    def _published_before_retrieved(self) -> Self:
        if self.published_at is not None and self.published_at > self.retrieved_at:
            raise ValueError("published_at is after retrieved_at")
        return self


class EvidenceItem(Contract):
    evidence_id: str = Field(default="", description="SHA-256 of all other fields; auto-filled.")
    event_id: str = Field(min_length=1)
    category: EvidenceCategory
    claim_kind: ClaimKind
    extracted_fact: str = Field(min_length=1, max_length=500)
    excerpt: str | None = Field(default=None, max_length=MAX_EXCERPT_CHARS)
    source: SourceSnapshot
    derived_from: tuple[str, ...] = Field(
        default=(), description="evidence_ids an INFERENCE was derived from."
    )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.claim_kind is ClaimKind.INFERENCE and not self.derived_from:
            raise ValueError("an INFERENCE must cite the evidence it was derived from")
        if self.claim_kind is not ClaimKind.INFERENCE and self.derived_from:
            raise ValueError("only an INFERENCE may set derived_from")
        _seal(self, "evidence_id")
        return self


class ProviderFailure(Contract):
    """A provider that failed during collection; kept so partial failures stay visible."""

    provider: str = Field(min_length=1)
    kind: ProviderErrorKind
    message: str
    occurred_at: AwareDatetime

    @field_validator("occurred_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)


class EvidenceSnapshot(Contract):
    """The exact evidence used for one event at one moment. Never mutated; newer data = new one."""

    snapshot_id: str = Field(default="", description="SHA-256 of all other fields; auto-filled.")
    event_id: str = Field(min_length=1)
    created_at: AwareDatetime
    items: tuple[EvidenceItem, ...]
    failures: tuple[ProviderFailure, ...] = ()

    @field_validator("created_at")
    @classmethod
    def _to_utc(cls, value: datetime) -> datetime:
        return value.astimezone(UTC)

    @model_validator(mode="after")
    def _check(self) -> Self:
        ids = [item.evidence_id for item in self.items]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate evidence items")
        known = set(ids)
        for item in self.items:
            if item.event_id != self.event_id:
                raise ValueError(f"evidence {item.evidence_id} belongs to event {item.event_id}")
            if item.source.retrieved_at > self.created_at:
                raise ValueError(f"evidence {item.evidence_id} retrieved after snapshot creation")
            if missing := set(item.derived_from) - known:
                raise ValueError(f"inference cites evidence not in snapshot: {sorted(missing)}")
        _seal(self, "snapshot_id")
        return self
