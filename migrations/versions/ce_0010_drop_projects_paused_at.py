# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0010_drop_projects_paused_at"
down_revision = "ce_0009_drop_per_user_skills_tracking_add_system_announce"
branch_labels = None
depends_on = None


PROJECTS_TABLE = "projects"
COL_PAUSED_AT = "paused_at"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, PROJECTS_TABLE, COL_PAUSED_AT):
        op.drop_column(PROJECTS_TABLE, COL_PAUSED_AT)


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, PROJECTS_TABLE, COL_PAUSED_AT):
        op.add_column(
            PROJECTS_TABLE,
            sa.Column(COL_PAUSED_AT, sa.DateTime(timezone=True), nullable=True),
        )
