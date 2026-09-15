# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import inspect, text


revision = "ce_0091_backfill_product_agent_assignments"
down_revision = "ce_0090_heal_giljo_hq_orchestrator_identity"
branch_labels = None
depends_on = None


_BACKFILL_SQL = text(
    """
    INSERT INTO product_agent_assignments (id, product_id, template_id, tenant_key, is_active)
    SELECT gen_random_uuid()::text, p.id, t.id, p.tenant_key, TRUE
    FROM products p
    JOIN agent_templates t
      ON t.tenant_key = p.tenant_key
    WHERE p.deleted_at IS NULL
      AND t.deleted_at IS NULL
      AND t.is_active IS TRUE
      AND NOT EXISTS (
          SELECT 1
          FROM product_agent_assignments a
          WHERE a.product_id = p.id
            AND a.template_id = t.id
      )
    """
)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    tables = set(inspector.get_table_names())

    if not {"product_agent_assignments", "products", "agent_templates"} <= tables:
        return

    result = bind.execute(_BACKFILL_SQL)
    print(f"ce_0091: backfilled {result.rowcount} product agent assignment(s)")  # noqa: T201


def downgrade() -> None:
    pass
