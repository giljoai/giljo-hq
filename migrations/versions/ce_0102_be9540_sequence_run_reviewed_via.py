# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "ce_0102_be9540_sequence_run_reviewed_via"
down_revision = "ce_0101_fe9530_comm_thread_project_tags"
branch_labels = None
depends_on = None


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
    if not _column_exists(conn, "reviewed_via"):
        op.add_column(
            "sequence_runs",
            sa.Column(
                "reviewed_via",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("sequence_runs", "reviewed_via")
