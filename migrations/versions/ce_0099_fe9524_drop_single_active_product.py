# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
    op.execute("ALTER TABLE public.products ADD COLUMN IF NOT EXISTS is_default boolean NOT NULL DEFAULT false")
    op.execute(f"COMMENT ON COLUMN public.products.is_default IS '{_DEFAULT_COMMENT}'")

    op.execute("UPDATE public.products SET is_default = true WHERE is_active = true AND is_default = false")

    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_NEW_INDEX} ON public.products USING btree (tenant_key) "
        "WHERE (is_default = true)"
    )

    op.execute(f"DROP INDEX IF EXISTS {_OLD_INDEX}")

    op.execute(f"COMMENT ON COLUMN public.products.is_active IS '{_NEW_ACTIVE_COMMENT}'")


def downgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_NEW_INDEX}")
    op.execute("ALTER TABLE public.products DROP COLUMN IF EXISTS is_default")
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_OLD_INDEX} ON public.products USING btree (tenant_key) "
        "WHERE (is_active = true)"
    )
    op.execute(f"COMMENT ON COLUMN public.products.is_active IS '{_OLD_ACTIVE_COMMENT}'")
