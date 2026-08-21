# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Drop vision_document_summaries (BE-5117b).

Revision ID: ce_0035_drop_vision_document_summaries
Revises: ce_0034_update_is_summarized_comment
Create Date: 2026-05-27

BE-5117b collapses the parallel vision-summary write paths down to the
column-based path introduced in BE-5117. The legacy table
``vision_document_summaries`` is no longer written or read at runtime;
all per-document summaries live in ``vision_documents.summary_light /
summary_medium`` and the product aggregate in
``products.consolidated_vision_light / consolidated_vision_medium``.

Idempotency: ``DROP TABLE IF EXISTS`` and existence checks on the
``COMMENT ON COLUMN`` refresh.

Downgrade: rebuilds the original table shape (mirrors the baseline at
v37 / pre-BE-5117b). The data is NOT restored on downgrade -- rows were
already throwaway on the test install, and the hosted prod
vision_document_summaries table was empty at the time of the rollout.

Edition Scope: Both -- the ``vision_documents`` / ``vision_document_summaries``
tables are CE models shared by SaaS via the CE chain.
"""

import sqlalchemy as sa
from alembic import op


revision = "ce_0035_drop_vision_document_summaries"
down_revision = "ce_0034_update_is_summarized_comment"
branch_labels = None
depends_on = None


TABLE = "vision_document_summaries"
IS_SUMMARIZED_COMMENT_NEW = (
    "True once the per-document agent summaries (summary_light + summary_medium) "
    "have been populated on this row via update_product_fields."
)
IS_SUMMARIZED_COMMENT_PREV = (
    "Legacy: pre-BE-5117 Sumy-based summary flag. Now indicates: vision "
    "document has a summary in vision_document_summaries (AI-tool-generated)."
)


def _table_exists(conn, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if _table_exists(conn, TABLE):
        op.execute(sa.text(f"DROP TABLE {TABLE} CASCADE"))

    op.execute(
        sa.text("COMMENT ON COLUMN vision_documents.is_summarized IS :c").bindparams(c=IS_SUMMARIZED_COMMENT_NEW)
    )


def downgrade() -> None:
    conn = op.get_bind()

    if not _table_exists(conn, TABLE):
        op.create_table(
            TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=255), nullable=False),
            sa.Column(
                "document_id",
                sa.String(length=36),
                sa.ForeignKey("vision_documents.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "product_id",
                sa.String(length=36),
                sa.ForeignKey("products.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("source", sa.String(length=20), nullable=False),
            sa.Column("ratio", sa.Numeric(3, 2), nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("tokens_original", sa.Integer(), nullable=False),
            sa.Column("tokens_summary", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        )
        op.create_index("idx_vds_lookup", TABLE, ["tenant_key", "document_id", "source", "ratio"])
        op.create_index("idx_vds_product", TABLE, ["tenant_key", "product_id"])

    op.execute(
        sa.text("COMMENT ON COLUMN vision_documents.is_summarized IS :c").bindparams(c=IS_SUMMARIZED_COMMENT_PREV)
    )
