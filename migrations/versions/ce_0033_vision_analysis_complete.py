# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0033_vision_analysis_complete"
down_revision = "ce_0032_vision_docs_inline_only"
branch_labels = None
depends_on = None


TABLE = "products"
COLUMN = "vision_analysis_complete"


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
                sa.Boolean(),
                nullable=False,
                server_default=sa.text("false"),
                comment=(
                    "True when all per-doc + product-aggregate summaries are populated. "
                    "Gates project staging UX (BE-5118)."
                ),
            ),
        )

    conn.execute(
        sa.text(
            "UPDATE products SET vision_analysis_complete = TRUE "
            "WHERE consolidated_vision_light IS NOT NULL "
            "OR consolidated_vision_medium IS NOT NULL"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
