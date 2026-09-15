# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0016_tasks_drop_category"
down_revision = "ce_0015_tasks_add_task_type_id"
branch_labels = None
depends_on = None


TASKS_TABLE = "tasks"
COL = "category"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, TASKS_TABLE, COL):
        op.drop_column(TASKS_TABLE, COL)


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, TASKS_TABLE, COL):
        op.add_column(TASKS_TABLE, sa.Column(COL, sa.String(100), nullable=True))
