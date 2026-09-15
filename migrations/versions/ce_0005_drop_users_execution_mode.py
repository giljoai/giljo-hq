# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0005_drop_users_execution_mode"
down_revision = "ce_0004_projects_product_id_not_null"
branch_labels = None
depends_on = None


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()
    if _has_column(conn, "users", "execution_mode"):
        op.drop_column("users", "execution_mode")


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_column(conn, "users", "execution_mode"):
        op.add_column(
            "users",
            sa.Column(
                "execution_mode",
                sa.String(length=20),
                nullable=False,
                server_default="claude_code",
            ),
        )
