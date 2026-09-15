# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "ce_0039_create_notifications"
down_revision = "ce_0038_drop_projects_activated_at_deactivation_reason"
branch_labels = None
depends_on = None


NOTIFICATIONS_TABLE = "notifications"
DEDUPE_INDEX = "uq_notifications_tenant_dedupe_open"
LIST_INDEX = "idx_notifications_tenant_user_created"
TENANT_INDEX = "idx_notifications_tenant_key"
DEDUPE_KEY_INDEX = "idx_notifications_dedupe_key"


def _has_table(conn, table: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :table"),
        {"table": table},
    )
    return result.first() is not None


def _has_index(conn, index: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :index"),
        {"index": index},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_table(conn, NOTIFICATIONS_TABLE):
        op.create_table(
            NOTIFICATIONS_TABLE,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column(
                "user_id",
                sa.String(length=36),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                nullable=True,
            ),
            sa.Column("type", sa.String(length=100), nullable=False),
            sa.Column("severity", sa.String(length=20), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False),
            sa.Column("body", sa.Text(), nullable=True),
            sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
            sa.Column("dedupe_key", sa.String(length=255), nullable=False),
            sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            ),
        )

    if not _has_index(conn, TENANT_INDEX):
        op.create_index(TENANT_INDEX, NOTIFICATIONS_TABLE, ["tenant_key"])

    if not _has_index(conn, DEDUPE_KEY_INDEX):
        op.create_index(DEDUPE_KEY_INDEX, NOTIFICATIONS_TABLE, ["dedupe_key"])

    if not _has_index(conn, DEDUPE_INDEX):
        op.create_index(
            DEDUPE_INDEX,
            NOTIFICATIONS_TABLE,
            ["tenant_key", "dedupe_key"],
            unique=True,
            postgresql_where=sa.text("resolved_at IS NULL"),
        )

    if not _has_index(conn, LIST_INDEX):
        op.create_index(
            LIST_INDEX,
            NOTIFICATIONS_TABLE,
            ["tenant_key", "user_id", sa.text("created_at DESC")],
        )


def downgrade() -> None:
    conn = op.get_bind()

    for index in (LIST_INDEX, DEDUPE_INDEX, DEDUPE_KEY_INDEX, TENANT_INDEX):
        if _has_index(conn, index):
            op.drop_index(index, table_name=NOTIFICATIONS_TABLE)

    if _has_table(conn, NOTIFICATIONS_TABLE):
        op.drop_table(NOTIFICATIONS_TABLE)
