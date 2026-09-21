"""create append-only intake_records table

Revision ID: 0002
Revises: 0001
Create Date: 2026-09-21
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "intake_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("state", sa.Text(), nullable=False),
        sa.Column("original_input", sa.Text(), nullable=True),
        sa.Column("result", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("bet_slip_id", sa.Uuid(), nullable=True),
        sa.Column("supersedes_id", sa.Uuid(), nullable=True),
        sa.CheckConstraint("source IN ('manual', 'paste')", name="ck_intake_records_source"),
        sa.CheckConstraint(
            "state IN ('RESOLVED', 'NEEDS_RESOLUTION', 'REJECTED')",
            name="ck_intake_records_state",
        ),
        sa.CheckConstraint(
            "bet_slip_id IS NULL OR state = 'RESOLVED'",
            name="ck_intake_records_slip_only_when_resolved",
        ),
        sa.ForeignKeyConstraint(["bet_slip_id"], ["bet_slips.id"]),
        sa.ForeignKeyConstraint(["supersedes_id"], ["intake_records.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_intake_records_received_at", "intake_records", ["received_at"])


def downgrade() -> None:
    op.drop_index("ix_intake_records_received_at", table_name="intake_records")
    op.drop_table("intake_records")
