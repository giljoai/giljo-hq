# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "ce_0063_login_lockouts"
down_revision = "ce_0062_sequence_run_conductor_columns"
branch_labels = None
depends_on = None


TABLE = "login_lockouts"


def _has_table(conn, table: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
            {"t": table},
        ).first()
        is not None
    )


def upgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, TABLE):
        return

    op.create_table(
        TABLE,
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("identifier", sa.String(length=255), nullable=False),
        sa.Column("ip_address", sa.String(length=45), nullable=False),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("first_failed_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("identifier", "ip_address", name="uq_login_lockout_identifier_ip"),
    )
    op.create_index("idx_login_lockout_identifier", TABLE, ["identifier"])
    op.create_index("idx_login_lockout_locked_until", TABLE, ["locked_until"])


def downgrade() -> None:
    op.drop_index("idx_login_lockout_locked_until", table_name=TABLE)
    op.drop_index("idx_login_lockout_identifier", table_name=TABLE)
    op.drop_table(TABLE)
