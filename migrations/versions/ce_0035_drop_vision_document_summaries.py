# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
