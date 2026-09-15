# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0048_roadmap_item_blocked"
down_revision = "ce_0047_roadmaps"
branch_labels = None
depends_on = None


ROADMAP_ITEMS = "roadmap_items"


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

    if not _has_column(conn, ROADMAP_ITEMS, "blocked"):
        op.add_column(
            ROADMAP_ITEMS,
            sa.Column(
                "blocked",
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
            ),
        )

    if not _has_column(conn, ROADMAP_ITEMS, "blocked_reason"):
        op.add_column(
            ROADMAP_ITEMS,
            sa.Column("blocked_reason", sa.Text(), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, ROADMAP_ITEMS, "blocked_reason"):
        op.drop_column(ROADMAP_ITEMS, "blocked_reason")

    if _has_column(conn, ROADMAP_ITEMS, "blocked"):
        op.drop_column(ROADMAP_ITEMS, "blocked")
