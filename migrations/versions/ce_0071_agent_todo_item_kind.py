# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0071_agent_todo_item_kind"
down_revision = "ce_0070_comm_participant_read_cursor"
branch_labels = None
depends_on = None


def _column_exists(conn, column_name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.columns"
                "  WHERE table_name = 'agent_todo_items'"
                "  AND column_name = :col"
                ")"
            ),
            {"col": column_name},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if not _column_exists(conn, "todo_kind"):
        op.add_column("agent_todo_items", sa.Column("todo_kind", sa.String(32), nullable=True))


def downgrade() -> None:
    conn = op.get_bind()
    if _column_exists(conn, "todo_kind"):
        op.drop_column("agent_todo_items", "todo_kind")
