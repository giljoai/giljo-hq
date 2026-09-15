# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0050_roadmap_sort_order"
down_revision = "ce_0049_heal_tool_rename_user_instructions"
branch_labels = None
depends_on = None


ROADMAP_ITEMS = "roadmap_items"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, ROADMAP_ITEMS, "priority") and not _has_column(conn, ROADMAP_ITEMS, "sort_order"):
        op.alter_column(ROADMAP_ITEMS, "priority", new_column_name="sort_order")


def downgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, ROADMAP_ITEMS, "sort_order") and not _has_column(conn, ROADMAP_ITEMS, "priority"):
        op.alter_column(ROADMAP_ITEMS, "sort_order", new_column_name="priority")
