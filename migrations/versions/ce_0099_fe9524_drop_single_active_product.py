# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9524/D1: is_active becomes Show/Hide; the read-fallback guarantee moves to a new is_default column.

Revision ID: ce_0099_fe9524_drop_single_active_product
Revises: ce_0098_be9514_approval_decided_via_channel
Create Date: 2026-08-29

WHY. Per the 2026-08-28 multi-product design decision (D1), "active product"
is retired as a user-facing concept. ``products.is_active`` is REUSED, not
deleted -- old meaning "the one active product per tenant", new meaning
"shown as a tab in my strip". Several products may be shown at once, so the
per-tenant uniqueness ``idx_product_single_active_per_tenant`` enforced no
longer holds and this migration drops it.

THE SPLIT (operator ruling, 2026-08-29, added to this migration after the
first draft only dropped the index). Dropping that index without a
replacement would leave ``ProductRepository.get_active_product`` -- the
fallback every unscoped read uses (``list_tasks``, ``list_projects``,
``get_roadmap``, ``resolve_binding_product``'s no-``product_id`` branch, and
more) -- querying ``is_active`` with ``scalar_one_or_none()``, which raises
``MultipleResultsFound`` the instant a tenant shows a second product. "Shown"
and "the one thing an unscoped read resolves to" are two different questions
and need two different columns:

- ``is_active`` -- SHOWN/HIDDEN, several per tenant, no enforcement (this
  migration's index drop).
- ``is_default`` (NEW) -- DEFAULT, exactly one per tenant, enforced by the
  NEW ``idx_product_single_default_per_tenant`` partial unique index. This is
  the single-row guarantee ``idx_product_single_active_per_tenant`` used to
  provide, moved onto a column that keeps a single unscoped-read target
  honest instead of papering over a now-multi-row query with ``LIMIT 1``.

SEQUENCING (this is why the four statements below run in this order, not
column-then-drop). The backfill and the new index are created WHILE the OLD
index still holds "at most one is_active=true per tenant" -- so the backfill
can only ever produce at most one is_default=true per tenant, and the new
unique index is guaranteed to succeed. Only THEN is the old index dropped.
Reversing that order would create a window where a second shown product
could exist before the new index is in place to prevent a second default.

BACKFILL. ``UPDATE products SET is_default = true WHERE is_active = true``:
the tenant's one historically-active product becomes both shown AND default,
which is the operator-approved migration behavior and keeps every
single-product tenant's unscoped reads working exactly as before -- "single-
product users see no change" holds for the default resolution too, not just
for shown/hidden.

EDGES, STATED (not code -- these are read-tolerance behaviors, not asserted
by this migration): a tenant whose historical product was never activated
(is_active was already false pre-migration) gets NO default from this
backfill. ``ProductRepository.get_default_product`` separately tolerates a
genuinely fresh (or migrated-with-no-default) tenant that has exactly ONE
SHOWN product -- that sole-shown-product fallback, not an auto-default on
create, is what keeps "single-product users see no change" true for reads.
``ProductService.create_product`` deliberately does NOT auto-set
``is_default``, even for a tenant's first product: default is independent of
shown/hidden, so a row this call auto-defaulted would disagree with
``is_active`` the moment that product is later hidden (hiding must not
silently clear an explicit default, but nothing should silently SET one
either -- see product_service.py's ``create_product`` docstring). A deleted
or hidden default is not reassigned by this migration or by any service
code -- "no default" (``get_default_product`` returns ``None``) is an
existing, already-tolerated state (pre-D1, "no active product" was legal
too), and D2 means a hidden default is still exactly as valid a
target as a shown one.

IDEMPOTENT. Every statement uses ``IF NOT EXISTS``/``IF EXISTS`` or is a
naturally-converging ``UPDATE``, so a rerun (CE's every-boot
``alembic upgrade``) is a no-op once applied.

Edition Scope: CE (``products`` is a CE core table; SaaS runs the CE chain).
"""

from alembic import op


revision = "ce_0099_fe9524_drop_single_active_product"
down_revision = "ce_0098_be9514_approval_decided_via_channel"
branch_labels = None
depends_on = None

_OLD_INDEX = "idx_product_single_active_per_tenant"
_NEW_INDEX = "idx_product_single_default_per_tenant"
_OLD_ACTIVE_COMMENT = "Active product for token estimation and mission planning (one per tenant)"
_NEW_ACTIVE_COMMENT = "Shown as a tab in the product tab strip (FE-9524/D1). A new product is shown by default."
_DEFAULT_COMMENT = (
    "The single per-tenant default product: where an unscoped read resolves. Independent of is_active/shown."
)


def upgrade() -> None:
    # 1. Add the new column while the OLD index still guarantees <=1
    #    is_active=true per tenant.
    op.execute("ALTER TABLE public.products ADD COLUMN IF NOT EXISTS is_default boolean NOT NULL DEFAULT false")
    op.execute(f"COMMENT ON COLUMN public.products.is_default IS '{_DEFAULT_COMMENT}'")

    # 2. Backfill: today's sole active product becomes the default too.
    op.execute("UPDATE public.products SET is_default = true WHERE is_active = true AND is_default = false")

    # 3. New single-row guarantee, created while step 1's precondition still holds.
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_NEW_INDEX} ON public.products USING btree (tenant_key) "
        "WHERE (is_default = true)"
    )

    # 4. Only now drop the old index -- is_active may freely become multi-valued.
    op.execute(f"DROP INDEX IF EXISTS {_OLD_INDEX}")

    # Parity with the baseline_v38_unified.py column comment edit -- both
    # paths (fresh install and full chain replay) must converge on the same
    # comment (tests/integration/migrations/test_inf5060_squash_baseline_v38.py).
    op.execute(f"COMMENT ON COLUMN public.products.is_active IS '{_NEW_ACTIVE_COMMENT}'")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_NEW_INDEX}")
    op.execute("ALTER TABLE public.products DROP COLUMN IF EXISTS is_default")
    # Schema-only revert. Re-creating the UNIQUE index will fail if any tenant
    # currently shows more than one product -- that is the correct behavior:
    # a downgrade must not silently hide products to satisfy the constraint.
    # An operator downgrading past this point is expected to hide down to one
    # shown product per tenant first.
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_OLD_INDEX} ON public.products USING btree (tenant_key) "
        "WHERE (is_active = true)"
    )
    op.execute(f"COMMENT ON COLUMN public.products.is_active IS '{_OLD_ACTIVE_COMMENT}'")
