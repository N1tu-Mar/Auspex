"""Append-only tables for the analysis workflow (migrations 0003-0006).

Every table is insert-only: a database trigger rejects UPDATE, DELETE, and TRUNCATE (see
`database/migrations/versions/20260921_0003_append_only_guard.py`). Identity tables hold what
never changes; anything mutable is a new snapshot row. Column shapes mirror `auspex_contracts`.
"""

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, ForeignKeyConstraint, Index, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

TS = DateTime(timezone=True)
SHA256 = r"'^[0-9a-f]{64}$'"


class SourceRecord(Base):
    """Provider/source metadata for one retrieval; referenced by snapshots and evidence."""

    __tablename__ = "sources"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(Text)
    publisher: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(TS)
    retrieved_at: Mapped[datetime] = mapped_column(TS)
    content_sha256: Mapped[str | None] = mapped_column(Text)


class EventRecord(Base):
    __tablename__ = "events"
    __table_args__ = (
        CheckConstraint("sport IN ('NFL', 'NCAAF', 'MLB', 'SOCCER')", name="ck_events_sport"),
    )

    event_id: Mapped[str] = mapped_column(Text, primary_key=True)
    sport: Mapped[str] = mapped_column(Text)
    league: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS)


class EventSnapshotRecord(Base):
    __tablename__ = "event_snapshots"
    __table_args__ = (
        CheckConstraint(
            "status IN ('PREGAME', 'LIVE', 'COMPLETED', 'POSTPONED', 'CANCELED', 'UNSUPPORTED')",
            name="ck_event_snapshots_status",
        ),
        Index("ix_event_snapshots_event_captured", "event_id", "captured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id"))
    captured_at: Mapped[datetime] = mapped_column(TS)
    event_start_utc: Mapped[datetime] = mapped_column(TS)
    status: Mapped[str] = mapped_column(Text)
    home_participant: Mapped[str | None] = mapped_column(Text)
    away_participant: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))


class MarketRecord(Base):
    __tablename__ = "markets"
    __table_args__ = (
        CheckConstraint(
            "market_type IS NULL OR market_type IN ('MONEYLINE', 'SPREAD', 'TOTAL', 'PLAYER_PROP')",
            name="ck_markets_market_type",
        ),
    )

    provider: Mapped[str] = mapped_column(Text, primary_key=True)
    market_id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id"), index=True)
    market_type: Mapped[str | None] = mapped_column(Text)
    provider_market_type: Mapped[str | None] = mapped_column(Text)
    line: Mapped[Decimal | None]
    slug: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(TS)


class MarketSnapshotRecord(Base):
    __tablename__ = "market_snapshots"
    __table_args__ = (
        ForeignKeyConstraint(["provider", "market_id"], ["markets.provider", "markets.market_id"]),
        CheckConstraint(
            "best_bid_usd IS NULL OR (best_bid_usd > 0 AND best_bid_usd < 1)",
            name="ck_market_snapshots_bid_range",
        ),
        CheckConstraint(
            "best_ask_usd IS NULL OR (best_ask_usd > 0 AND best_ask_usd < 1)",
            name="ck_market_snapshots_ask_range",
        ),
        CheckConstraint(
            "best_bid_usd IS NULL OR best_ask_usd IS NULL OR best_bid_usd <= best_ask_usd",
            name="ck_market_snapshots_bid_le_ask",
        ),
        Index("ix_market_snapshots_market_captured", "provider", "market_id", "captured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    provider: Mapped[str] = mapped_column(Text)
    market_id: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(TS)
    title: Mapped[str | None] = mapped_column(Text)
    is_open: Mapped[bool]
    combo_enabled: Mapped[bool | None]
    best_bid_usd: Mapped[Decimal | None]
    best_ask_usd: Mapped[Decimal | None]
    fee_coefficient: Mapped[Decimal | None]
    sides: Mapped[list[dict[str, Any]]] = mapped_column(JSONB)
    warnings: Mapped[list[str]] = mapped_column(JSONB)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))


class EvidenceItemRecord(Base):
    """Content-addressed: `id` is the SHA-256 `evidence_id`, so re-inserting is a no-op."""

    __tablename__ = "evidence_items"
    __table_args__ = (
        CheckConstraint(f"id ~ {SHA256}", name="ck_evidence_items_id_sha256"),
        CheckConstraint(
            "category IN ('MARKET', 'ODDS', 'STATS', 'NEWS', 'WEATHER', 'INJURY', 'LINEUP')",
            name="ck_evidence_items_category",
        ),
        CheckConstraint(
            "claim_kind IN ('CONFIRMED_FACT', 'PROJECTION', 'RUMOR', 'OPINION', 'INFERENCE')",
            name="ck_evidence_items_claim_kind",
        ),
        CheckConstraint(
            "(claim_kind = 'INFERENCE') = (jsonb_array_length(derived_from) > 0)",
            name="ck_evidence_items_inference_cites",
        ),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id"), index=True)
    category: Mapped[str] = mapped_column(Text)
    claim_kind: Mapped[str] = mapped_column(Text)
    extracted_fact: Mapped[str] = mapped_column(Text)
    excerpt: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("sources.id"))
    derived_from: Mapped[list[str]] = mapped_column(JSONB)


class EvidenceSnapshotRecord(Base):
    """Content-addressed set of evidence items used for one event at one moment."""

    __tablename__ = "evidence_snapshots"
    __table_args__ = (
        CheckConstraint(f"id ~ {SHA256}", name="ck_evidence_snapshots_id_sha256"),
        Index("ix_evidence_snapshots_event_created", "event_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id"))
    created_at: Mapped[datetime] = mapped_column(TS)


class EvidenceSnapshotItemRecord(Base):
    """Snapshot membership. `position` preserves order, which the snapshot hash depends on."""

    __tablename__ = "evidence_snapshot_items"

    snapshot_id: Mapped[str] = mapped_column(ForeignKey("evidence_snapshots.id"), primary_key=True)
    position: Mapped[int] = mapped_column(primary_key=True)
    evidence_id: Mapped[str] = mapped_column(ForeignKey("evidence_items.id"), index=True)


class ProviderFailureRecord(Base):
    """A failed provider call. `snapshot_id` is set when the failure belongs to a snapshot."""

    __tablename__ = "provider_failures"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('TIMEOUT', 'RATE_LIMITED', 'UNAVAILABLE', 'NOT_FOUND', 'BAD_REQUEST', "
            "'SCHEMA')",
            name="ck_provider_failures_kind",
        ),
        Index("ix_provider_failures_provider_occurred", "provider", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_snapshots.id"), index=True)
    provider: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)
    message: Mapped[str] = mapped_column(Text)
    occurred_at: Mapped[datetime] = mapped_column(TS)


class FeatureSnapshotRecord(Base):
    __tablename__ = "feature_snapshots"
    __table_args__ = (
        CheckConstraint(
            "sport IN ('NFL', 'NCAAF', 'MLB', 'SOCCER')", name="ck_feature_snapshots_sport"
        ),
        Index("ix_feature_snapshots_event_captured", "event_id", "captured_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.event_id"))
    sport: Mapped[str] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(TS)
    feature_set_version: Mapped[str] = mapped_column(Text)
    evidence_snapshot_id: Mapped[str | None] = mapped_column(ForeignKey("evidence_snapshots.id"))
    features: Mapped[dict[str, Any]] = mapped_column(JSONB)


class AnalysisRunRecord(Base):
    """One complete analysis of one saved slip. Re-analysis inserts a new run."""

    __tablename__ = "analysis_runs"
    __table_args__ = (
        CheckConstraint(
            "recommendation IN ('CONSIDER', 'PASS', 'AVOID', 'INSUFFICIENT_DATA')",
            name="ck_analysis_runs_recommendation",
        ),
        CheckConstraint(
            "(recommendation = 'INSUFFICIENT_DATA') = (insufficient_reasons IS NOT NULL)",
            name="ck_analysis_runs_reasons_iff_insufficient",
        ),
        CheckConstraint(
            "insufficient_reasons IS NULL OR jsonb_array_length(insufficient_reasons) > 0",
            name="ck_analysis_runs_reasons_not_empty",
        ),
        CheckConstraint("as_of_utc <= created_at", name="ck_analysis_runs_as_of_le_created"),
        Index("ix_analysis_runs_slip_as_of", "bet_slip_id", "as_of_utc"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(TS)
    as_of_utc: Mapped[datetime] = mapped_column(TS)
    bet_slip_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("bet_slips.id"))
    intake_record_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("intake_records.id"))
    code_version: Mapped[str] = mapped_column(Text)
    model_version: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    recommendation_reason: Mapped[str] = mapped_column(Text)
    insufficient_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    combo: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    expected_value: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class AnalysisLegRecord(Base):
    """Per-leg result. `leg_index` points into the saved slip's `legs` array."""

    __tablename__ = "analysis_legs"
    __table_args__ = (
        CheckConstraint("leg_index >= 0", name="ck_analysis_legs_index"),
        CheckConstraint(
            "market_implied_probability BETWEEN 0 AND 1"
            " AND (consensus_probability IS NULL OR consensus_probability BETWEEN 0 AND 1)",
            name="ck_analysis_legs_probability_range",
        ),
        CheckConstraint(
            "(model_probability IS NULL) = (insufficient_reasons IS NOT NULL)"
            " AND (model_probability IS NULL) = (probability_low IS NULL)"
            " AND (model_probability IS NULL) = (probability_high IS NULL)"
            " AND (model_probability IS NULL) = (estimate_model_version IS NULL)"
            " AND (model_probability IS NULL) = (estimate_snapshot_captured_at IS NULL)"
            " AND (model_probability IS NULL) = (edge_probability_points IS NULL)",
            name="ck_analysis_legs_estimate_xor_insufficient",
        ),
        CheckConstraint(
            "model_probability IS NULL OR (0 <= probability_low"
            " AND probability_low <= model_probability"
            " AND model_probability <= probability_high AND probability_high <= 1)",
            name="ck_analysis_legs_interval",
        ),
        CheckConstraint(
            "insufficient_reasons IS NULL OR jsonb_array_length(insufficient_reasons) > 0",
            name="ck_analysis_legs_reasons_not_empty",
        ),
    )

    analysis_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("analysis_runs.id"), primary_key=True)
    leg_index: Mapped[int] = mapped_column(primary_key=True)
    market_implied_probability: Mapped[Decimal]
    consensus_probability: Mapped[Decimal | None]
    model_probability: Mapped[Decimal | None]
    probability_low: Mapped[Decimal | None]
    probability_high: Mapped[Decimal | None]
    estimate_model_version: Mapped[str | None] = mapped_column(Text)
    estimate_snapshot_captured_at: Mapped[datetime | None] = mapped_column(TS)
    edge_probability_points: Mapped[Decimal | None]
    insufficient_reasons: Mapped[list[str] | None] = mapped_column(JSONB)
    event_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("event_snapshots.id"), index=True
    )
    market_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("market_snapshots.id"), index=True
    )
    evidence_snapshot_id: Mapped[str | None] = mapped_column(
        ForeignKey("evidence_snapshots.id"), index=True
    )
    feature_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("feature_snapshots.id"), index=True
    )
