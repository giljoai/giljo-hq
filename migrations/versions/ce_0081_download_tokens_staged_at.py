# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Download tokens: add per-token ``staged_at`` staleness anchor.

Revision ID: ce_0081_download_tokens_staged_at
Revises: ce_0080_widen_comm_agent_id_columns
Create Date: 2026-07-18

TSK-9210 -- closes the two-overlapping-tokens edge that BE-9208's tenant-global
export watermark cannot catch. With two live download tokens and a template edit
between their stagings, the NEWER staging's ``MAX(last_exported_at)`` masks the
OLDER link's staleness, so the older link serves a pre-change snapshot with a
200. ``staged_at`` records when THIS token's ZIP was staged, letting the guard
compare the tenant's content watermark against the token's own staging time.

Operations
----------
1. Add nullable ``staged_at`` (DateTime(timezone=True)) to ``download_tokens``
   (existence-guarded).

Chain routing
-------------
``download_tokens`` is a CE table (``src/giljo_mcp/models/config.py``), so this
lives in ``migrations/versions/`` (the CE chain), NEVER ``saas_versions/``.
Paired with a parity edit to ``baseline_v38_unified.py`` declaring the same
column LAST in the download_tokens create_table -- this migration appends it, so
declaring it last in the baseline keeps the fresh-install and chain-replay
schemas byte-identical (the INF-5060 parity invariant covers column ORDER).
Precedent: ce_0079.

Idempotency
-----------
The column add is guarded by an ``inspect()`` column-existence check. The CE
installer reruns the chain on every boot, so every step must be re-runnable.

Data-facing DoD
---------------
Additive only: one nullable column, no default, NO BACKFILL. Tolerance rather
than data surgery (rule (a)) -- tokens minted before this upgrade keep
``staged_at IS NULL`` and the guard falls back to the BE-9208 export-watermark
comparison for them, so no existing row is invalid and no in-flight download
link breaks. Tokens expire after 15 minutes, so the legacy path self-drains
almost immediately rather than being a permanent second code path.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0081_download_tokens_staged_at"
down_revision = "ce_0080_widen_comm_agent_id_columns"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("download_tokens")]

    if "staged_at" not in columns:
        op.add_column(
            "download_tokens",
            sa.Column(
                "staged_at",
                sa.DateTime(timezone=True),
                nullable=True,
                comment="TSK-9210: when this token's ZIP was staged; anchors per-token staleness",
            ),
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    columns = [c["name"] for c in inspector.get_columns("download_tokens")]

    if "staged_at" in columns:
        op.drop_column("download_tokens", "staged_at")
