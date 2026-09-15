# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0034_update_is_summarized_comment"
down_revision = "ce_0033_vision_analysis_complete"
branch_labels = None
depends_on = None


NEW_COMMENT = (
    "Legacy: pre-BE-5117 Sumy-based summary flag. Now indicates: vision "
    "document has a summary in vision_document_summaries (AI-tool-generated)."
)
OLD_COMMENT = "Has document been summarized using LSA algorithm"


def upgrade() -> None:
    op.execute(f"COMMENT ON COLUMN vision_documents.is_summarized IS '{NEW_COMMENT}'")


def downgrade() -> None:
    op.execute(f"COMMENT ON COLUMN vision_documents.is_summarized IS '{OLD_COMMENT}'")
