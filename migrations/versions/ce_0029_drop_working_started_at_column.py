# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0029_drop_working_started_at_column"
down_revision = "ce_0028_agent_executions_add_working_started_at"
branch_labels = None
depends_on = None


TABLE = "agent_executions"
COLUMN = "working_started_at"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.DateTime(timezone=True),
                nullable=True,
            ),
        )
