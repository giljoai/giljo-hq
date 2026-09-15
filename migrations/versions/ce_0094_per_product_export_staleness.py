# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import inspect, text


revision = "ce_0094_per_product_export_staleness"
down_revision = "ce_0093_drop_export_alias"
branch_labels = None
depends_on = None


_ASSIGNMENTS = "product_agent_assignments"
_TEMPLATES = "agent_templates"

_COMMENT = "BE-9385e: when THIS product last exported this agent (NULL falls back to the template)"

_BACKFILL_SQL = text(
    """
    UPDATE product_agent_assignments AS a
    SET last_exported_at = t.last_exported_at
    FROM agent_templates AS t
    WHERE a.template_id = t.id
      AND a.tenant_key = t.tenant_key
      AND a.last_exported_at IS NULL
      AND t.last_exported_at IS NOT NULL
    """
)


def _columns(inspector, table: str) -> set[str]:
    return {c["name"] for c in inspector.get_columns(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if _ASSIGNMENTS not in tables:
        return

    if "last_exported_at" not in _columns(inspector, _ASSIGNMENTS):
        op.execute(f"ALTER TABLE {_ASSIGNMENTS} ADD COLUMN last_exported_at TIMESTAMP WITH TIME ZONE")
    op.execute(f"COMMENT ON COLUMN {_ASSIGNMENTS}.last_exported_at IS '{_COMMENT}'")

    if _TEMPLATES not in tables:
        return

    backfilled = bind.execute(_BACKFILL_SQL).rowcount
    print(f"ce_0094: backfilled {backfilled} per-product export timestamp(s)")  # noqa: T201


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if _ASSIGNMENTS in tables and "last_exported_at" in _columns(inspector, _ASSIGNMENTS):
        op.execute(f"ALTER TABLE {_ASSIGNMENTS} DROP COLUMN last_exported_at")
