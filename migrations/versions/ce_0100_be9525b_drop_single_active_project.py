# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0100_be9525b_drop_single_active_project"
down_revision = "ce_0099_fe9524_drop_single_active_product"
branch_labels = None
depends_on = None

_INDEX = "idx_project_single_active_per_product"


def upgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")


def downgrade() -> None:
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX} ON public.projects USING btree (product_id) "
        "WHERE (status = 'active'::public.project_status)"
    )
