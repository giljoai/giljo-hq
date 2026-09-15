# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0036_add_ctx_taxonomy_type"
down_revision = "ce_0035_drop_vision_document_summaries"
branch_labels = None
depends_on = None


CTX_ABBREVIATION = "CTX"
CTX_LABEL = "Context Update"
CTX_COLOR = "#9E9E9E"
CTX_SORT_ORDER = 8


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            INSERT INTO taxonomy_types (
                id, tenant_key, abbreviation, label, color, sort_order,
                created_at, updated_at
            )
            SELECT
                gen_random_uuid()::text,
                t.tenant_key,
                :abbr,
                :label,
                :color,
                :sort_order,
                NOW(),
                NOW()
            FROM (SELECT DISTINCT tenant_key FROM taxonomy_types) AS t
            ON CONFLICT (tenant_key, abbreviation) DO NOTHING
            """
        ).bindparams(
            abbr=CTX_ABBREVIATION,
            label=CTX_LABEL,
            color=CTX_COLOR,
            sort_order=CTX_SORT_ORDER,
        )
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            DELETE FROM taxonomy_types
            WHERE abbreviation = :abbr
              AND NOT EXISTS (
                  SELECT 1 FROM projects
                  WHERE projects.project_type_id = taxonomy_types.id
              )
            """
        ).bindparams(abbr=CTX_ABBREVIATION)
    )
