# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0107_db9639_drop_tasks_due_date"
down_revision = "ce_0106_be9637_mcp_tool_call_metrics"
branch_labels = None
depends_on = None

_TASKS = "tasks"


def upgrade() -> None:
    op.execute(f"ALTER TABLE IF EXISTS {_TASKS} DROP COLUMN IF EXISTS due_date")


def downgrade() -> None:
    op.execute(f"ALTER TABLE IF EXISTS {_TASKS} ADD COLUMN IF NOT EXISTS due_date TIMESTAMP WITH TIME ZONE")
