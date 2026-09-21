# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0105_db9607_drop_template_export_columns"
down_revision = "ce_0104_be9610a_product_owned_agent_copies"
branch_labels = None
depends_on = None

_TEMPLATES = "agent_templates"
_ASSIGNMENTS = "product_agent_assignments"


def upgrade() -> None:
    op.execute(f"ALTER TABLE IF EXISTS {_TEMPLATES} DROP COLUMN IF EXISTS last_exported_at")
    op.execute(f"ALTER TABLE IF EXISTS {_TEMPLATES} DROP COLUMN IF EXISTS user_managed_export")
    op.execute(f"ALTER TABLE IF EXISTS {_ASSIGNMENTS} DROP COLUMN IF EXISTS last_exported_at")


def downgrade() -> None:
    op.execute(f"ALTER TABLE IF EXISTS {_TEMPLATES} ADD COLUMN IF NOT EXISTS last_exported_at TIMESTAMP WITH TIME ZONE")
    op.execute(f"ALTER TABLE IF EXISTS {_TEMPLATES} ADD COLUMN IF NOT EXISTS user_managed_export BOOLEAN")
    op.execute(f"ALTER TABLE IF EXISTS {_ASSIGNMENTS} ADD COLUMN IF NOT EXISTS last_exported_at TIMESTAMP WITH TIME ZONE")
