# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0028_agent_executions_add_working_started_at"
down_revision = "ce_0027_backfill_active_staging_orch_phase"
branch_labels = None
depends_on = None


TABLE = "agent_executions"
COLUMN = "working_started_at"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.DateTime(timezone=True),
                nullable=True,
                comment=(
                    "Set once on first waiting→working transition; reset only on "
                    "complete→working reactivation. Anchor for duration_seconds."
                ),
            ),
        )

    op.execute(
        sa.text(
            "UPDATE agent_executions SET working_started_at = started_at "
            "WHERE working_started_at IS NULL AND status <> 'waiting' "
            "AND started_at IS NOT NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
