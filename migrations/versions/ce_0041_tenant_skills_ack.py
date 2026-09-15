# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0041_tenant_skills_ack"
down_revision = "ce_0040_notifications_banner_columns"
branch_labels = None
depends_on = None


TABLE = "tenant_skills_ack"


def _has_table(conn, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_table(conn, TABLE):
        op.create_table(
            TABLE,
            sa.Column("tenant_key", sa.String(length=255), primary_key=True),
            sa.Column("acknowledged_version", sa.String(length=128), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("CURRENT_TIMESTAMP"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_table(conn, TABLE):
        op.drop_table(TABLE)
