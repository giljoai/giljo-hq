# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "ce_0058_sequence_runs"
down_revision = "ce_0057_comm_thread_soft_delete"
branch_labels = None
depends_on = None


def _table_exists(conn, table: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT EXISTS (SELECT FROM information_schema.tables WHERE table_name = :t)"),
            {"t": table},
        ).scalar()
    )


def upgrade() -> None:
    conn = op.get_bind()
    if _table_exists(conn, "sequence_runs"):
        return

    op.create_table(
        "sequence_runs",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("tenant_key", sa.String(36), nullable=False),
        sa.Column("project_ids", JSONB, nullable=False),
        sa.Column("resolved_order", JSONB, nullable=False),
        sa.Column("current_index", sa.Integer, nullable=False, server_default="0"),
        sa.Column("execution_mode", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("review_policy", sa.String(30), nullable=False, server_default="per_card"),
        sa.Column("project_statuses", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )

    op.create_index("idx_sequence_runs_tenant", "sequence_runs", ["tenant_key"])


def downgrade() -> None:
    conn = op.get_bind()
    if not _table_exists(conn, "sequence_runs"):
        return
    op.drop_index("idx_sequence_runs_tenant", table_name="sequence_runs")
    op.drop_table("sequence_runs")
