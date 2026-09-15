# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0024_tasks_add_hidden"
down_revision = "ce_0023_tasks_shared_taxonomy_serial"
branch_labels = None
depends_on = None


TASKS_TABLE = "tasks"
HIDDEN_COL = "hidden"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, TASKS_TABLE, HIDDEN_COL):
        op.add_column(
            TASKS_TABLE,
            sa.Column(
                HIDDEN_COL,
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
                comment="Whether task is hidden from default list view (UI declutter only)",
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, TASKS_TABLE, HIDDEN_COL):
        op.drop_column(TASKS_TABLE, HIDDEN_COL)
