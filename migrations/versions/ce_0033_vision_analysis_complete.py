# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Add products.vision_analysis_complete flag (BE-5117 Phase 1).

Revision ID: ce_0033_vision_analysis_complete
Revises: ce_0032_vision_docs_inline_only
Create Date: 2026-05-27

BE-5117 strips Sumy/NLTK from the product. Per-document and product-aggregate
summaries are now written exclusively by the AI agent via the
``update_product_fields`` MCP tool. The new column gates project staging UX
(BE-5118) — TRUE only when every active vision document and the product
aggregate both have light + medium summaries populated.

Backfill rule (design decision): legacy products with non-NULL Sumy-era
consolidated summaries are marked TRUE. New uploads start FALSE until the
agent writes the summaries.

Idempotency: existence-checks before any DDL — the CE installer reruns
migrations on every boot.

Downgrade: drops the column (existence-checked).

Edition Scope: Both -- the ``products`` table is a CE model shared by SaaS
via the CE chain.
"""

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

    # Backfill: legacy Sumy-era rows with consolidated summaries are considered complete.
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
