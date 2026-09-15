# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0017_tasks_add_series_number_subseries"
down_revision = "ce_0016_tasks_drop_category"
branch_labels = None
depends_on = None


TASKS_TABLE = "tasks"
SERIES_COL = "series_number"
SUBSERIES_COL = "subseries"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, TASKS_TABLE, SERIES_COL):
        op.add_column(
            TASKS_TABLE,
            sa.Column(SERIES_COL, sa.Integer(), nullable=True),
        )

    if not _has_column(conn, TASKS_TABLE, SUBSERIES_COL):
        op.add_column(
            TASKS_TABLE,
            sa.Column(SUBSERIES_COL, sa.String(length=1), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, TASKS_TABLE, SUBSERIES_COL):
        op.drop_column(TASKS_TABLE, SUBSERIES_COL)

    if _has_column(conn, TASKS_TABLE, SERIES_COL):
        op.drop_column(TASKS_TABLE, SERIES_COL)
