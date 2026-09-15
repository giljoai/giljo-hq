# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0038_drop_projects_activated_at_deactivation_reason"
down_revision = "ce_0037_seed_agent_silence_threshold_system_setting"
branch_labels = None
depends_on = None


PROJECTS_TABLE = "projects"
COL_ACTIVATED_AT = "activated_at"
COL_DEACTIVATION_REASON = "deactivation_reason"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, PROJECTS_TABLE, COL_ACTIVATED_AT):
        op.drop_column(PROJECTS_TABLE, COL_ACTIVATED_AT)
    if _has_column(conn, PROJECTS_TABLE, COL_DEACTIVATION_REASON):
        op.drop_column(PROJECTS_TABLE, COL_DEACTIVATION_REASON)


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, PROJECTS_TABLE, COL_ACTIVATED_AT):
        op.add_column(
            PROJECTS_TABLE,
            sa.Column(
                COL_ACTIVATED_AT,
                sa.DateTime(timezone=True),
                nullable=True,
                comment="First activation timestamp (only set once on first activation)",
            ),
        )
    if not _has_column(conn, PROJECTS_TABLE, COL_DEACTIVATION_REASON):
        op.add_column(
            PROJECTS_TABLE,
            sa.Column(
                COL_DEACTIVATION_REASON,
                sa.Text(),
                nullable=True,
                comment="Reason for project deactivation",
            ),
        )
