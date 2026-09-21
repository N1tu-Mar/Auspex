"""add append-only guard trigger and apply it to existing tables

Revision ID: 0003
Revises: 0002
Create Date: 2026-09-21
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tables that already exist. Each later migration guards its own tables with the same call.
EXISTING = ("bet_slips", "intake_records")


def upgrade() -> None:
    op.execute(
        """
        CREATE FUNCTION forbid_row_change() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'table % is append-only: % is not allowed', TG_TABLE_NAME, TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$
        """
    )
    # guard_append_only(table): reject UPDATE, DELETE, and TRUNCATE. Dropping the table still works.
    op.execute(
        """
        CREATE FUNCTION guard_append_only(tbl regclass) RETURNS void LANGUAGE plpgsql AS $$
        DECLARE name text := split_part(tbl::text, '.', 2);
        BEGIN
            IF name = '' THEN name := tbl::text; END IF;
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE UPDATE OR DELETE ON %s '
                'FOR EACH ROW EXECUTE FUNCTION forbid_row_change()',
                name || '_append_only_rows', tbl);
            EXECUTE format(
                'CREATE TRIGGER %I BEFORE TRUNCATE ON %s '
                'FOR EACH STATEMENT EXECUTE FUNCTION forbid_row_change()',
                name || '_append_only_truncate', tbl);
        END;
        $$
        """
    )
    for table in EXISTING:
        op.execute(f"SELECT guard_append_only('{table}')")


def downgrade() -> None:
    for table in EXISTING:
        op.execute(f"DROP TRIGGER {table}_append_only_truncate ON {table}")
        op.execute(f"DROP TRIGGER {table}_append_only_rows ON {table}")
    op.execute("DROP FUNCTION guard_append_only(regclass)")
    op.execute("DROP FUNCTION forbid_row_change()")
