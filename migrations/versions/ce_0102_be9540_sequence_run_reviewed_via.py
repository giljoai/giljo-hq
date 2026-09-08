# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Add ``reviewed_via`` JSONB to sequence_runs (BE-9540).

Revision ID: ce_0102_be9540_sequence_run_reviewed_via
Revises: ce_0101_fe9530_comm_thread_project_tags
Create Date: 2026-08-30

Per-member review PROVENANCE map ({project_id -> "ui" | "harness"}), mirroring
the shape of UserApproval.decided_via ("which door" recorded which member's
review). Added so a headlessly-completed per_card chain can be auto-marked
reviewed at conductor-finale time (satisfied-by-harness) without ever silently
bypassing the review policy the dashboard flow enforces -- the operator-visible
symptom this closes: a run purging with reviewed_project_ids still empty because
the headless path never wrote it at all.

Non-null with ``server_default='{}'`` so existing rows (created before this
column) converge to the safe empty-map state without a backfill -- data-shape
self-heal via a default, matching the ce_0077 reviewed_project_ids precedent.
Idempotent (existence-checked) because the CE installer reruns migrations on
every boot; reversible (downgrade drops it).

``sequence_runs`` is a CE table (created in ce_0058) and is NOT part of any
baseline snapshot taken before this column existed, so there is no baseline
block to mirror here -- a fresh install runs baseline -> ... -> ce_0058
(creates the table) -> ce_0102 (adds this column) and converges to the
identical shape as an upgraded deployment. Belongs in the CE ``versions/``
chain.
"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision = "ce_0102_be9540_sequence_run_reviewed_via"
down_revision = "ce_0101_fe9530_comm_thread_project_tags"
branch_labels = None
depends_on = None


def _column_exists(conn, column_name: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS ("
                "  SELECT FROM information_schema.columns"
                "  WHERE table_name = 'sequence_runs'"
                "  AND column_name = :col"
                ")"
            ),
            {"col": column_name},
        ).scalar()
    )


def upgrade() -> None:
    # Idempotency guard: add the column only if absent (CE reruns on boot).
    conn = op.get_bind()
    if not _column_exists(conn, "reviewed_via"):
        op.add_column(
            "sequence_runs",
            sa.Column(
                "reviewed_via",
                postgresql.JSONB(),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )


def downgrade() -> None:
    op.drop_column("sequence_runs", "reviewed_via")
