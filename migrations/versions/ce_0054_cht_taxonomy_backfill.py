# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import text


revision = "ce_0054_cht_taxonomy_backfill"
down_revision = "ce_0053_comm_hub_tables"
branch_labels = None
depends_on = None


_CHT_ABBR = "CHT"
_CHT_LABEL = "Chat Thread"
_CHT_COLOR = "#1565C0"
_CHT_SORT_ORDER = 101


def upgrade() -> None:
    op.execute(
        text(
            """
            INSERT INTO taxonomy_types
                (id, tenant_key, abbreviation, label, color, sort_order, created_at, updated_at)
            SELECT
                gen_random_uuid()::text, t.tenant_key, :abbr, :label, :color, :sort_order,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM (SELECT DISTINCT tenant_key FROM taxonomy_types) t
            WHERE NOT EXISTS (
                SELECT 1 FROM taxonomy_types x
                WHERE x.tenant_key = t.tenant_key AND x.abbreviation = :abbr
            )
            """
        ).bindparams(
            abbr=_CHT_ABBR,
            label=_CHT_LABEL,
            color=_CHT_COLOR,
            sort_order=_CHT_SORT_ORDER,
        )
    )


def downgrade() -> None:
    op.execute(text("DELETE FROM taxonomy_types WHERE abbreviation = :abbr").bindparams(abbr=_CHT_ABBR))
