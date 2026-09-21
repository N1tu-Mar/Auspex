"""create append-only source, event, and market identity and snapshot tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NUM = sa.Numeric()
TABLES = ("sources", "events", "event_snapshots", "markets", "market_snapshots")


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("publisher", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("published_at", TS, nullable=True),
        sa.Column("retrieved_at", TS, nullable=False),
        sa.Column("content_sha256", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "events",
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("league", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint("sport IN ('NFL', 'NCAAF', 'MLB', 'SOCCER')", name="ck_events_sport"),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_table(
        "event_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("captured_at", TS, nullable=False),
        sa.Column("event_start_utc", TS, nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("home_participant", sa.Text(), nullable=True),
        sa.Column("away_participant", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "status IN ('PREGAME', 'LIVE', 'COMPLETED', 'POSTPONED', 'CANCELED', 'UNSUPPORTED')",
            name="ck_event_snapshots_status",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.event_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_event_snapshots_event_captured", "event_snapshots", ["event_id", "captured_at"]
    )
    op.create_table(
        "markets",
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("market_type", sa.Text(), nullable=True),
        sa.Column("provider_market_type", sa.Text(), nullable=True),
        sa.Column("line", NUM, nullable=True),
        sa.Column("slug", sa.Text(), nullable=True),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(
            "market_type IS NULL OR market_type IN ('MONEYLINE', 'SPREAD', 'TOTAL', 'PLAYER_PROP')",
            name="ck_markets_market_type",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.event_id"]),
        sa.PrimaryKeyConstraint("provider", "market_id"),
    )
    op.create_index("ix_markets_event_id", "markets", ["event_id"])
    op.create_table(
        "market_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("market_id", sa.Text(), nullable=False),
        sa.Column("captured_at", TS, nullable=False),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("is_open", sa.Boolean(), nullable=False),
        sa.Column("combo_enabled", sa.Boolean(), nullable=True),
        sa.Column("best_bid_usd", NUM, nullable=True),
        sa.Column("best_ask_usd", NUM, nullable=True),
        sa.Column("fee_coefficient", NUM, nullable=True),
        sa.Column("sides", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("warnings", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.CheckConstraint(
            "best_bid_usd IS NULL OR (best_bid_usd > 0 AND best_bid_usd < 1)",
            name="ck_market_snapshots_bid_range",
        ),
        sa.CheckConstraint(
            "best_ask_usd IS NULL OR (best_ask_usd > 0 AND best_ask_usd < 1)",
            name="ck_market_snapshots_ask_range",
        ),
        sa.CheckConstraint(
            "best_bid_usd IS NULL OR best_ask_usd IS NULL OR best_bid_usd <= best_ask_usd",
            name="ck_market_snapshots_bid_le_ask",
        ),
        sa.ForeignKeyConstraint(
            ["provider", "market_id"], ["markets.provider", "markets.market_id"]
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_market_snapshots_market_captured",
        "market_snapshots",
        ["provider", "market_id", "captured_at"],
    )
    for table in TABLES:
        op.execute(f"SELECT guard_append_only('{table}')")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
