# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Backfill product_agent_assignments so every product has an explicit agent set.

Revision ID: ce_0091_backfill_product_agent_assignments
Revises: ce_0090_heal_giljo_hq_orchestrator_identity
Create Date: 2026-08-09

BE-9385a -- the ``product_agent_assignments`` junction becomes authoritative for
which agents a product exports and can spawn. Before this, selection was
tenant-wide everywhere, so the junction was populated only by product
ACTIVATION (``product_lifecycle_service.py:183-201``), and that write is
best-effort ``try/except`` (``:202-207``). Two populations therefore hold zero
rows: products created before the junction existed, and products whose
activation-time assignment silently failed.

Those products are not broken after this upgrade -- selection tolerates a
row-less product by falling back to the tenant-active set (see
``repositories/product_agent_selection.py``). This migration exists so the state
is EXPLICIT rather than implied: with rows present, the Agents screen can show
and curate a real per-product set, and the first toggle changes one agent instead
of materialising a set as a side effect.

Operations
----------
1. Insert one ``is_active=True`` row per (live product, tenant-active live
   template) pair that does not already have one.

Chain routing
-------------
``product_agent_assignments`` is a CE table
(``src/giljo_mcp/models/product_agent_assignment.py``), so this belongs in
``migrations/versions/``, never ``saas_versions/``. **No schema change** -- data
only -- so there is no paired ``baseline_v38_unified.py`` edit and the INF-5060
parity invariant is untouched.

Idempotency
-----------
The CE installer reruns the chain on every boot, so this must be re-runnable.
``WHERE NOT EXISTS`` against the existing (product_id, template_id) pair is the
guard; it is also what the unique constraint ``uq_product_template_assignment``
would otherwise enforce by raising. A second run inserts zero rows.

The table-existence check is belt-and-braces for a DB stamped mid-chain where
the table has not been created yet.

Data-facing DoD
---------------
Additive only, and deliberately **skip-existing**: a row a user has already set
to ``is_active=False`` is never touched, so an agent deliberately disabled for a
product stays disabled across this upgrade, across a CE boot re-seed, and across
re-activation of that product. That is the same guarantee
``bulk_assign_all_templates`` already provides, and it is why this is an insert of
missing pairs rather than a refresh.

Deliberately NOT backfilled: templates that are tenant-INACTIVE or soft-deleted.
Selection ANDs the junction with the template's own live/active state anyway, so
rows for them would be inert -- and creating them would quietly re-enable an
agent for every product the moment the user reactivated it tenant-wide.
"""

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
    # Deliberately a no-op. The rows this inserts are indistinguishable from the
    # ones product activation writes, so a downgrade cannot tell them apart --
    # and deleting the union would discard the user's own per-product curation.
    # Selection tolerates row-less products, so leaving the rows in place is safe
    # on a downgraded schema.
    pass
