# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0007_users_skills_version_tracking"
down_revision = "ce_0006_configurations_unique_tenant_key"
branch_labels = None
depends_on = None


TABLE_NAME = "users"
COL_VERSION = "last_installed_skills_version"
COL_REMINDER = "last_update_reminder_at"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, TABLE_NAME, COL_VERSION):
        op.add_column(
            TABLE_NAME,
            sa.Column(COL_VERSION, sa.String(length=32), nullable=True),
        )

    if not _has_column(conn, TABLE_NAME, COL_REMINDER):
        op.add_column(
            TABLE_NAME,
            sa.Column(COL_REMINDER, sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, TABLE_NAME, COL_REMINDER):
        op.drop_column(TABLE_NAME, COL_REMINDER)

    if _has_column(conn, TABLE_NAME, COL_VERSION):
        op.drop_column(TABLE_NAME, COL_VERSION)
