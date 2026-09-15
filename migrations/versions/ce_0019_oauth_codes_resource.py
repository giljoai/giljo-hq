# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0019_oauth_codes_resource"
down_revision = "ce_0018_user_approvals"
branch_labels = None
depends_on = None


TABLE = "oauth_authorization_codes"
COLUMN = "resource"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(COLUMN, sa.String(length=2048), nullable=True),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_column(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
