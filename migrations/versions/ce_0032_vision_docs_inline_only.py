# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

import sqlalchemy as sa
from alembic import op


logger = logging.getLogger(__name__)


revision = "ce_0032_vision_docs_inline_only"
down_revision = "ce_0031_user_split_name"
branch_labels = None
depends_on = None


TABLE = "vision_documents"
OLD_STORAGE_CHECK = "ck_vision_doc_storage_type"
OLD_CONSISTENCY_CHECK = "ck_vision_doc_storage_consistency"
NEW_INLINE_CHECK = "ck_vision_doc_inline_only"


def _has_check_constraint(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :name "
            "AND constraint_type = 'CHECK'"
        ),
        {"table": table, "name": constraint},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    orphan_rows = conn.execute(
        sa.text("SELECT id FROM vision_documents WHERE storage_type IN ('file', 'hybrid') AND vision_document IS NULL")
    ).all()
    if orphan_rows:
        logger.warning(
            "BE-5115 backfill: %d vision_documents rows had NULL vision_document under "
            "storage_type IN ('file','hybrid'); resetting to '' so the inline CHECK accepts them. "
            "Affected ids: %s",
            len(orphan_rows),
            [r[0] for r in orphan_rows],
        )
        conn.execute(
            sa.text(
                "UPDATE vision_documents SET vision_document = '' "
                "WHERE storage_type IN ('file', 'hybrid') AND vision_document IS NULL"
            )
        )

    conn.execute(
        sa.text(
            "UPDATE vision_documents "
            "SET storage_type = 'inline', vision_path = NULL "
            "WHERE storage_type IN ('file', 'hybrid')"
        )
    )

    if _has_check_constraint(conn, TABLE, OLD_CONSISTENCY_CHECK):
        op.drop_constraint(OLD_CONSISTENCY_CHECK, TABLE, type_="check")

    if _has_check_constraint(conn, TABLE, OLD_STORAGE_CHECK):
        op.drop_constraint(OLD_STORAGE_CHECK, TABLE, type_="check")

    op.create_check_constraint(
        OLD_STORAGE_CHECK,
        TABLE,
        "storage_type = 'inline'",
    )

    if not _has_check_constraint(conn, TABLE, NEW_INLINE_CHECK):
        op.create_check_constraint(
            NEW_INLINE_CHECK,
            TABLE,
            "storage_type = 'inline' AND vision_document IS NOT NULL AND vision_path IS NULL",
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_check_constraint(conn, TABLE, NEW_INLINE_CHECK):
        op.drop_constraint(NEW_INLINE_CHECK, TABLE, type_="check")

    if _has_check_constraint(conn, TABLE, OLD_STORAGE_CHECK):
        op.drop_constraint(OLD_STORAGE_CHECK, TABLE, type_="check")

    op.create_check_constraint(
        OLD_STORAGE_CHECK,
        TABLE,
        "storage_type IN ('file', 'inline', 'hybrid')",
    )

    if not _has_check_constraint(conn, TABLE, OLD_CONSISTENCY_CHECK):
        op.create_check_constraint(
            OLD_CONSISTENCY_CHECK,
            TABLE,
            "(storage_type = 'file' AND vision_path IS NOT NULL) OR "
            "(storage_type = 'inline' AND vision_document IS NOT NULL) OR "
            "(storage_type = 'hybrid' AND vision_path IS NOT NULL AND vision_document IS NOT NULL)",
        )
