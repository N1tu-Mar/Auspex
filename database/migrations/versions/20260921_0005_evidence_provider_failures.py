"""create append-only evidence item, evidence snapshot, and provider failure tables

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
JSONB = postgresql.JSONB(astext_type=sa.Text())
SHA256 = r"'^[0-9a-f]{64}$'"
TABLES = ("evidence_items", "evidence_snapshots", "evidence_snapshot_items", "provider_failures")


def upgrade() -> None:
    op.create_table(
        "evidence_items",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("claim_kind", sa.Text(), nullable=False),
        sa.Column("extracted_fact", sa.Text(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Uuid(), nullable=False),
        sa.Column("derived_from", JSONB, nullable=False),
        sa.CheckConstraint(f"id ~ {SHA256}", name="ck_evidence_items_id_sha256"),
        sa.CheckConstraint(
            "category IN ('MARKET', 'ODDS', 'STATS', 'NEWS', 'WEATHER', 'INJURY', 'LINEUP')",
            name="ck_evidence_items_category",
        ),
        sa.CheckConstraint(
            "claim_kind IN ('CONFIRMED_FACT', 'PROJECTION', 'RUMOR', 'OPINION', 'INFERENCE')",
            name="ck_evidence_items_claim_kind",
        ),
        sa.CheckConstraint(
            "(claim_kind = 'INFERENCE') = (jsonb_array_length(derived_from) > 0)",
            name="ck_evidence_items_inference_cites",
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.event_id"]),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_evidence_items_event_id", "evidence_items", ["event_id"])
    op.create_table(
        "evidence_snapshots",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.CheckConstraint(f"id ~ {SHA256}", name="ck_evidence_snapshots_id_sha256"),
        sa.ForeignKeyConstraint(["event_id"], ["events.event_id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_snapshots_event_created", "evidence_snapshots", ["event_id", "created_at"]
    )
    op.create_table(
        "evidence_snapshot_items",
        sa.Column("snapshot_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("evidence_id", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["snapshot_id"], ["evidence_snapshots.id"]),
        sa.ForeignKeyConstraint(["evidence_id"], ["evidence_items.id"]),
        sa.PrimaryKeyConstraint("snapshot_id", "position"),
    )
    op.create_index(
        "ix_evidence_snapshot_items_evidence_id", "evidence_snapshot_items", ["evidence_id"]
    )
    op.create_table(
        "provider_failures",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("snapshot_id", sa.Text(), nullable=True),
        sa.Column("provider", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("occurred_at", TS, nullable=False),
        sa.CheckConstraint(
            "kind IN ('TIMEOUT', 'RATE_LIMITED', 'UNAVAILABLE', 'NOT_FOUND', 'BAD_REQUEST', "
            "'SCHEMA')",
            name="ck_provider_failures_kind",
        ),
        sa.ForeignKeyConstraint(["snapshot_id"], ["evidence_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_provider_failures_snapshot_id", "provider_failures", ["snapshot_id"])
    op.create_index(
        "ix_provider_failures_provider_occurred", "provider_failures", ["provider", "occurred_at"]
    )
    for table in TABLES:
        op.execute(f"SELECT guard_append_only('{table}')")


def downgrade() -> None:
    for table in (
        "provider_failures",
        "evidence_snapshot_items",
        "evidence_snapshots",
        "evidence_items",
    ):
        op.drop_table(table)
