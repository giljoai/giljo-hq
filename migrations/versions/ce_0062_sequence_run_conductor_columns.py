# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0062_sequence_run_conductor_columns"
down_revision = "ce_0061_message_loop_interval"
branch_labels = None
depends_on = None


_COLUMNS = (
    ("conductor_agent_id", sa.String(36)),
    ("conductor_project_id", sa.String(36)),
    ("conductor_label", sa.String(80)),
)


def _column_exists(conn, column_name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.columns"
                "  WHERE table_name = 'sequence_runs'"
                "  AND column_name = :col"
                ")"
            ),
            {"col": column_name},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    for name, coltype in _COLUMNS:
        if not _column_exists(conn, name):
            op.add_column("sequence_runs", sa.Column(name, coltype, nullable=True))


def downgrade() -> None:
    for name, _coltype in reversed(_COLUMNS):
        op.drop_column("sequence_runs", name)
