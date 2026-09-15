# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0040_notifications_banner_columns"
down_revision = "ce_0039_create_notifications"
branch_labels = None
depends_on = None


NOTIFICATIONS_TABLE = "notifications"
SURFACE_CHECK = "ck_notifications_surface"


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def _has_constraint(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :constraint"
        ),
        {"table": table, "constraint": constraint},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, NOTIFICATIONS_TABLE, "surface"):
        op.add_column(
            NOTIFICATIONS_TABLE,
            sa.Column("surface", sa.Text(), nullable=False, server_default=sa.text("'bell'")),
        )

    if not _has_column(conn, NOTIFICATIONS_TABLE, "role_filter"):
        op.add_column(NOTIFICATIONS_TABLE, sa.Column("role_filter", sa.Text(), nullable=True))

    if not _has_column(conn, NOTIFICATIONS_TABLE, "cta_label"):
        op.add_column(NOTIFICATIONS_TABLE, sa.Column("cta_label", sa.Text(), nullable=True))

    if not _has_column(conn, NOTIFICATIONS_TABLE, "cta_route"):
        op.add_column(NOTIFICATIONS_TABLE, sa.Column("cta_route", sa.Text(), nullable=True))

    if not _has_column(conn, NOTIFICATIONS_TABLE, "dismissible"):
        op.add_column(
            NOTIFICATIONS_TABLE,
            sa.Column("dismissible", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        )

    op.execute("UPDATE notifications SET surface = 'bell' WHERE surface IS NULL")

    if not _has_constraint(conn, NOTIFICATIONS_TABLE, SURFACE_CHECK):
        op.create_check_constraint(
            SURFACE_CHECK,
            NOTIFICATIONS_TABLE,
            "surface IN ('bell', 'banner', 'both')",
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_constraint(conn, NOTIFICATIONS_TABLE, SURFACE_CHECK):
        op.drop_constraint(SURFACE_CHECK, NOTIFICATIONS_TABLE, type_="check")

    for column in ("dismissible", "cta_route", "cta_label", "role_filter", "surface"):
        if _has_column(conn, NOTIFICATIONS_TABLE, column):
            op.drop_column(NOTIFICATIONS_TABLE, column)
