# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0056_server_runtime_metrics"
down_revision = "ce_0055_users_registration_ip"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    exists = conn.execute(
        sa.text("SELECT EXISTS (  SELECT FROM information_schema.tables  WHERE table_name = 'server_runtime_metrics')")
    ).scalar()
    if exists:
        return

    op.create_table(
        "server_runtime_metrics",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("worker_id", sa.String(length=128), nullable=False),
        sa.Column("metric", sa.String(length=64), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("worker_id", "metric", name="uq_server_runtime_metric_worker_metric"),
    )


def downgrade() -> None:
    op.drop_table("server_runtime_metrics")
