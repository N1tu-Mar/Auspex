"""create append-only feature snapshot, analysis run, and analysis leg tables

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TS = sa.DateTime(timezone=True)
NUM = sa.Numeric()
JSONB = postgresql.JSONB(astext_type=sa.Text())
TABLES = ("feature_snapshots", "analysis_runs", "analysis_legs")


def upgrade() -> None:
    op.create_table(
        "feature_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_id", sa.Text(), nullable=False),
        sa.Column("sport", sa.Text(), nullable=False),
        sa.Column("captured_at", TS, nullable=False),
        sa.Column("feature_set_version", sa.Text(), nullable=False),
        sa.Column("evidence_snapshot_id", sa.Text(), nullable=True),
        sa.Column("features", JSONB, nullable=False),
        sa.CheckConstraint(
            "sport IN ('NFL', 'NCAAF', 'MLB', 'SOCCER')", name="ck_feature_snapshots_sport"
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.event_id"]),
        sa.ForeignKeyConstraint(["evidence_snapshot_id"], ["evidence_snapshots.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_feature_snapshots_event_captured", "feature_snapshots", ["event_id", "captured_at"]
    )
    op.create_table(
        "analysis_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("created_at", TS, nullable=False),
        sa.Column("as_of_utc", TS, nullable=False),
        sa.Column("bet_slip_id", sa.Uuid(), nullable=False),
        sa.Column("intake_record_id", sa.Uuid(), nullable=True),
        sa.Column("code_version", sa.Text(), nullable=False),
        sa.Column("model_version", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("recommendation_reason", sa.Text(), nullable=False),
        sa.Column("insufficient_reasons", JSONB, nullable=True),
        sa.Column("combo", JSONB, nullable=True),
        sa.Column("expected_value", JSONB, nullable=True),
        sa.CheckConstraint(
            "recommendation IN ('CONSIDER', 'PASS', 'AVOID', 'INSUFFICIENT_DATA')",
            name="ck_analysis_runs_recommendation",
        ),
        sa.CheckConstraint(
            "(recommendation = 'INSUFFICIENT_DATA') = (insufficient_reasons IS NOT NULL)",
            name="ck_analysis_runs_reasons_iff_insufficient",
        ),
        sa.CheckConstraint(
            "insufficient_reasons IS NULL OR jsonb_array_length(insufficient_reasons) > 0",
            name="ck_analysis_runs_reasons_not_empty",
        ),
        sa.CheckConstraint("as_of_utc <= created_at", name="ck_analysis_runs_as_of_le_created"),
        sa.ForeignKeyConstraint(["bet_slip_id"], ["bet_slips.id"]),
        sa.ForeignKeyConstraint(["intake_record_id"], ["intake_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analysis_runs_slip_as_of", "analysis_runs", ["bet_slip_id", "as_of_utc"])
    op.create_table(
        "analysis_legs",
        sa.Column("analysis_id", sa.Uuid(), nullable=False),
        sa.Column("leg_index", sa.Integer(), nullable=False),
        sa.Column("market_implied_probability", NUM, nullable=False),
        sa.Column("consensus_probability", NUM, nullable=True),
        sa.Column("model_probability", NUM, nullable=True),
        sa.Column("probability_low", NUM, nullable=True),
        sa.Column("probability_high", NUM, nullable=True),
        sa.Column("estimate_model_version", sa.Text(), nullable=True),
        sa.Column("estimate_snapshot_captured_at", TS, nullable=True),
        sa.Column("edge_probability_points", NUM, nullable=True),
        sa.Column("insufficient_reasons", JSONB, nullable=True),
        sa.Column("event_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("market_snapshot_id", sa.Uuid(), nullable=True),
        sa.Column("evidence_snapshot_id", sa.Text(), nullable=True),
        sa.Column("feature_snapshot_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("leg_index >= 0", name="ck_analysis_legs_index"),
        sa.CheckConstraint(
            "market_implied_probability BETWEEN 0 AND 1"
            " AND (consensus_probability IS NULL OR consensus_probability BETWEEN 0 AND 1)",
            name="ck_analysis_legs_probability_range",
        ),
        sa.CheckConstraint(
            "(model_probability IS NULL) = (insufficient_reasons IS NOT NULL)"
            " AND (model_probability IS NULL) = (probability_low IS NULL)"
            " AND (model_probability IS NULL) = (probability_high IS NULL)"
            " AND (model_probability IS NULL) = (estimate_model_version IS NULL)"
            " AND (model_probability IS NULL) = (estimate_snapshot_captured_at IS NULL)"
            " AND (model_probability IS NULL) = (edge_probability_points IS NULL)",
            name="ck_analysis_legs_estimate_xor_insufficient",
        ),
        sa.CheckConstraint(
            "model_probability IS NULL OR (0 <= probability_low"
            " AND probability_low <= model_probability"
            " AND model_probability <= probability_high AND probability_high <= 1)",
            name="ck_analysis_legs_interval",
        ),
        sa.CheckConstraint(
            "insufficient_reasons IS NULL OR jsonb_array_length(insufficient_reasons) > 0",
            name="ck_analysis_legs_reasons_not_empty",
        ),
        sa.ForeignKeyConstraint(["analysis_id"], ["analysis_runs.id"]),
        sa.ForeignKeyConstraint(["event_snapshot_id"], ["event_snapshots.id"]),
        sa.ForeignKeyConstraint(["market_snapshot_id"], ["market_snapshots.id"]),
        sa.ForeignKeyConstraint(["evidence_snapshot_id"], ["evidence_snapshots.id"]),
        sa.ForeignKeyConstraint(["feature_snapshot_id"], ["feature_snapshots.id"]),
        sa.PrimaryKeyConstraint("analysis_id", "leg_index"),
    )
    for column in (
        "event_snapshot_id",
        "market_snapshot_id",
        "evidence_snapshot_id",
        "feature_snapshot_id",
    ):
        op.create_index(f"ix_analysis_legs_{column}", "analysis_legs", [column])
    for table in TABLES:
        op.execute(f"SELECT guard_append_only('{table}')")


def downgrade() -> None:
    for table in reversed(TABLES):
        op.drop_table(table)
