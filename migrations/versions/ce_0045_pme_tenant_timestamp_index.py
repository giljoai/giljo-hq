# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0045_pme_tenant_timestamp_index"
down_revision = "ce_0044_antigravity_tool_type"
branch_labels = None
depends_on = None


_INDEX_NAME = "idx_pme_tenant_timestamp"


def upgrade() -> None:
    op.execute(f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME} ON product_memory_entries (tenant_key, timestamp DESC)")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX_NAME}")
