# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Add product_agent_assignments.last_exported_at and backfill it.

Revision ID: ce_0094_per_product_export_staleness
Revises: ce_0093_drop_export_alias
Create Date: 2026-08-10

BE-9385e -- the "last exported" indicator must describe the product the user is
in. ``agent_templates.last_exported_at`` is tenant-wide, so exporting product A
stamped a column product B then displayed as its own: another product's action
reported as this product's state, on the one indicator that warns a user they are
shipping stale agents.

Why a per-product column and not just a tolerant read
-----------------------------------------------------
A NULL-fallback alone was analysed and rejected. It fixes nothing on its own,
because the tenant-wide column is not ABSENT -- it holds *someone else's truth*.
Product A's export sets it, and product B's NULL then falls back onto exactly the
wrong number. The fallback only becomes safe once this column exists AND every
export writes it for the exporting product; then NULL means "no per-product
record yet" rather than "nobody has exported".

The tenant-wide column deliberately STAYS. It is the fallback for rows this
backfill does not reach, and it is pre-existing information nobody authorised
discarding. Dropping it is a separate, destructive decision.

Chain routing
-------------
``product_agent_assignments`` is a CE table
(``src/giljo_mcp/models/product_agent_assignment.py``), so this belongs in
``migrations/versions/``, never ``saas_versions/``.

Baseline parity (INF-5060)
--------------------------
Unlike the data-only ce_0091, this migration CHANGES SCHEMA, so it is paired with
a matching ``baseline_v38_unified.py`` edit -- the ce_0092/ce_0081/ce_0043
precedent. A fresh install gets the column from the baseline; an existing DB gets
it from here; both converge on an identical shape. The column comment is part of
what the parity test compares, and ``ALTER TABLE ADD COLUMN`` does not carry one,
so ``COMMENT ON`` is issued here to match the baseline's declaration byte-for-byte.

Idempotency
-----------
The CE installer reruns the whole chain on every boot, so every step is
existence-guarded: the column is added only when absent, ``COMMENT ON`` is
naturally idempotent, and the backfill only touches rows whose value ``IS NULL``.
A second run does nothing and prints 0.

Data-facing DoD
---------------
"What happens to rows already in the old shape?" -- answered twice over, and
deliberately with BOTH acceptable answers rather than either alone:

(a) The code TOLERATES the old shape. A junction row with ``last_exported_at IS
    NULL`` reads the template's tenant-wide value (``effective_last_exported_at``
    in ``models/templates.py``). Nothing breaks if this backfill never runs, and
    nothing breaks for a row created after it.

(b) This backfill seeds the per-product column from the tenant-wide value, so the
    fallback is not load-bearing forever and a product's first export writes a
    real per-product record over a sensible starting point.

The backfill is additive and one-way: a row that already carries a value is never
rewritten, so re-running this after products have exported cannot roll their
timestamps backwards. Rows whose template was never exported stay NULL -- there is
nothing truthful to copy, and NULL correctly reads as "never exported" through the
fallback.

Seeding every product with the tenant-wide value does momentarily give a
never-exported product a timestamp it did not earn -- which is the very lie this
project fixes. It is nonetheless the right starting state: it is exactly what
those products display TODAY, so the upgrade changes nothing under the user's
feet, and the first export by any product replaces it with the truth. The
alternative -- backfilling NULL everywhere -- would flip every agent in every
product to "never exported" on upgrade, which is a louder and equally false claim.
"""

from alembic import op
from sqlalchemy import inspect, text


revision = "ce_0094_per_product_export_staleness"
down_revision = "ce_0093_drop_export_alias"
branch_labels = None
depends_on = None


_ASSIGNMENTS = "product_agent_assignments"
_TEMPLATES = "agent_templates"

# Must match the baseline's create_table comment byte-for-byte -- the INF-5060
# parity test compares column comments between the fast path and a chain replay.
_COMMENT = "BE-9385e: when THIS product last exported this agent (NULL falls back to the template)"

# Seed each junction row from its template's tenant-wide stamp. Only rows that
# have no value yet, and only where there is something truthful to copy.
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

    # Belt-and-braces for a DB stamped mid-chain where the table does not exist yet.
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
