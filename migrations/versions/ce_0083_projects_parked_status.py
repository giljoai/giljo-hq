# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Projects: add ``parked`` status value to the ``project_status`` ENUM.

Revision ID: ce_0083_projects_parked_status
Revises: ce_0082_oauth_refresh_origin_code_hash
Create Date: 2026-07-21

IMP-9258 -- ``parked`` project status: set a project aside without cancelling
it. Unlike ``superseded``/``cancelled``, parked is NOT lifecycle-finished
(stays visible in default project lists) and NOT immutable (a plain
``update_project(status='active'|'inactive')`` un-parks it -- no dedicated
restore endpoint or successor pointer needed). See
``giljo_mcp.domain.project_status.ProjectStatus.PARKED``.

Operations
----------
1. **Append ``'parked'`` to the ``project_status`` ENUM** via
   ``ALTER TYPE ... ADD VALUE IF NOT EXISTS``. Postgres appends new ENUM
   values to the END of the type, which matches the canonical declaration
   order in ``giljo_mcp.domain.project_status.ProjectStatus`` (PARKED is
   declared last, after SUPERSEDED) and the baseline's ``CREATE TYPE`` list.
   The value is NOT referenced anywhere else in this migration, so the PG12+
   "cannot use a new ENUM value in the same transaction" restriction does not
   apply.

No new column is needed -- unlike BE-9157's ``superseded`` (which carries a
``successor_project_id`` pointer), ``parked`` needs no extra state.

Chain routing
-------------
``status`` is a column on the CE ``Project`` model, so this lives in
``migrations/versions/`` (the CE chain), NEVER ``saas_versions/``. Paired
with a parity edit to ``baseline_v38_unified.py`` so a fresh install gets the
ENUM value directly.

Idempotency
-----------
``ADD VALUE IF NOT EXISTS`` is a no-op when the value already exists (fresh
install, where the baseline's ``CREATE TYPE`` already included it). The CE
installer reruns the chain on every boot, so this must be re-runnable.

Data-facing DoD
---------------
Additive only: a new ENUM value. Every existing row is untouched and remains
valid -- tolerant by construction, no backfill needed.
"""

from alembic import op


revision = "ce_0083_projects_parked_status"
down_revision = "ce_0082_oauth_refresh_origin_code_hash"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Append the 'parked' ENUM value (idempotent).
    op.execute("ALTER TYPE project_status ADD VALUE IF NOT EXISTS 'parked'")


def downgrade() -> None:
    # Postgres has no ``ALTER TYPE ... DROP VALUE``, and leaving an unused
    # ENUM value is harmless -- the 'parked' value is intentionally NOT
    # removed. Nothing else to reverse (no column, no FK, no data touched).
    pass
