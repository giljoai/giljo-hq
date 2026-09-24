# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0106_be9637_mcp_tool_call_metrics"
down_revision = "ce_0105_db9607_drop_template_export_columns"
branch_labels = None
depends_on = None


TABLE = "mcp_tool_call_metrics"


def _has_table(name: str) -> bool:
    return sa.inspect(op.get_bind()).has_table(name)


def upgrade() -> None:
    if _has_table(TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("tenant_key", sa.String(length=36), nullable=False),
        sa.Column("tool_name", sa.String(length=128), nullable=False),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("call_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tenant_key", "tool_name", "day", name="uq_mcp_tool_call_metric_tenant_tool_day"),
    )
    op.create_index(op.f(f"ix_{TABLE}_tenant_key"), TABLE, ["tenant_key"])
    op.create_index("idx_mcp_tool_call_metrics_tenant_day", TABLE, ["tenant_key", "day"])


def downgrade() -> None:
    if not _has_table(TABLE):
        return
    op.drop_index("idx_mcp_tool_call_metrics_tenant_day", table_name=TABLE)
    op.drop_index(op.f(f"ix_{TABLE}_tenant_key"), table_name=TABLE)
    op.drop_table(TABLE)
