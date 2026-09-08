# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9525b/D5: drop the single-active-project-per-product constraint (ruling 5 amended).

Revision ID: ce_0100_be9525b_drop_single_active_project
Revises: ce_0099_fe9524_drop_single_active_product
Create Date: 2026-08-29

WHY. Per the 2026-08-28 multi-product/multi-project decision record (D5,
amending ruling 5): N projects may be in-flight per product. The operator's
reasoning -- the app was arbitrarily forcing sequence; the real beginner
guardrail is the per-project staging pause (a server gate, untouched), not a
one-active-project ceiling. No replacement column is needed here (unlike
FE-9524/ce_0099's is_default split): nothing needs a single-row "the active
project" answer any more -- ``ProjectQueryService.get_active_project`` becomes
genuinely plural in this same project (application-layer change, not schema).

WHAT THIS DROPS. ``idx_project_single_active_per_product`` -- the partial
unique index on ``projects (product_id) WHERE status = 'active'`` -- recreated
by ce_0008 against the ENUM column after that migration's type conversion.
This migration drops the same index by name; it does not touch ce_0008's
history.

IDEMPOTENT. ``DROP INDEX IF EXISTS`` is a no-op on rerun (CE's every-boot
``alembic upgrade``).

Edition Scope: CE (``projects`` is a CE core table; SaaS runs the CE chain).
"""

from alembic import op


revision = "ce_0100_be9525b_drop_single_active_project"
down_revision = "ce_0099_fe9524_drop_single_active_product"
branch_labels = None
depends_on = None

_INDEX = "idx_project_single_active_per_product"


def upgrade() -> None:
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")


def downgrade() -> None:
    # Schema-only revert. Re-creating the UNIQUE index will fail if any
    # product currently has more than one ACTIVE project -- that is the
    # correct behavior: a downgrade must not silently deactivate projects to
    # satisfy the constraint. An operator downgrading past this point is
    # expected to deactivate down to one active project per product first.
    op.execute(
        f"CREATE UNIQUE INDEX IF NOT EXISTS {_INDEX} ON public.projects USING btree (product_id) "
        "WHERE (status = 'active'::public.project_status)"
    )
