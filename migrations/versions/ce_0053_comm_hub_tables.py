# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB


revision = "ce_0053_comm_hub_tables"
down_revision = "ce_0052_pme_fts_be6082"
branch_labels = None
depends_on = None


COMM_THREADS = "comm_threads"
COMM_PARTICIPANTS = "comm_participants"
MESSAGES = "messages"


def _has_table(conn, table: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = :t"),
            {"t": table},
        ).first()
        is not None
    )


def _has_column(conn, table: str, column: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
            {"t": table, "c": column},
        ).first()
        is not None
    )


def _is_nullable(conn, table: str, column: str) -> bool:
    row = conn.execute(
        sa.text("SELECT is_nullable FROM information_schema.columns WHERE table_name = :t AND column_name = :c"),
        {"t": table, "c": column},
    ).first()
    return bool(row) and row[0] == "YES"


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_table(conn, COMM_THREADS):
        op.create_table(
            COMM_THREADS,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column("serial", sa.Integer(), nullable=False),
            sa.Column("subject", sa.String(length=255), nullable=True),
            sa.Column("status", sa.String(length=50), nullable=False, server_default="open"),
            sa.Column("next_action_owner", sa.String(length=255), nullable=True),
            sa.Column("severity", sa.String(length=20), nullable=True),
            sa.Column(
                "product_id",
                sa.String(length=36),
                sa.ForeignKey("products.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column(
                "project_id",
                sa.String(length=36),
                sa.ForeignKey("projects.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("resolution", JSONB(), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("tenant_key", "serial", name="uq_comm_thread_serial"),
        )
        op.create_index("idx_comm_thread_tenant", COMM_THREADS, ["tenant_key"])
        op.create_index("idx_comm_thread_owner", COMM_THREADS, ["tenant_key", "next_action_owner"])
        op.create_index("idx_comm_thread_status", COMM_THREADS, ["tenant_key", "status"])
        op.create_index("idx_comm_thread_product", COMM_THREADS, ["product_id"])
        op.create_index("idx_comm_thread_project", COMM_THREADS, ["project_id"])

    if not _has_table(conn, COMM_PARTICIPANTS):
        op.create_table(
            COMM_PARTICIPANTS,
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("tenant_key", sa.String(length=36), nullable=False),
            sa.Column(
                "thread_id",
                sa.String(length=36),
                sa.ForeignKey("comm_threads.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("participant_id", sa.String(length=255), nullable=False),
            sa.Column("participant_type", sa.String(length=20), nullable=False),
            sa.Column("display_name", sa.String(length=255), nullable=True),
            sa.Column("role", sa.String(length=50), nullable=True),
            sa.Column("joined_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP")),
            sa.UniqueConstraint("thread_id", "participant_id", name="uq_comm_participant"),
        )
        op.create_index("idx_comm_participant_tenant", COMM_PARTICIPANTS, ["tenant_key"])
        op.create_index("idx_comm_participant_thread", COMM_PARTICIPANTS, ["thread_id"])
        op.create_index("idx_comm_participant_lookup", COMM_PARTICIPANTS, ["tenant_key", "participant_id"])

    if not _has_column(conn, MESSAGES, "thread_id"):
        op.add_column(
            MESSAGES,
            sa.Column(
                "thread_id",
                sa.String(length=36),
                sa.ForeignKey("comm_threads.id", ondelete="CASCADE"),
                nullable=True,
            ),
        )
        op.create_index("idx_message_thread", MESSAGES, ["thread_id"])

    if not _is_nullable(conn, MESSAGES, "project_id"):
        op.alter_column(MESSAGES, "project_id", existing_type=sa.String(length=36), nullable=True)


def downgrade() -> None:
    conn = op.get_bind()

    if _is_nullable(conn, MESSAGES, "project_id"):
        null_count = conn.execute(sa.text("SELECT COUNT(*) FROM messages WHERE project_id IS NULL")).scalar_one()
        if null_count == 0:
            op.alter_column(MESSAGES, "project_id", existing_type=sa.String(length=36), nullable=False)

    if _has_column(conn, MESSAGES, "thread_id"):
        op.drop_index("idx_message_thread", table_name=MESSAGES)
        op.drop_column(MESSAGES, "thread_id")

    if _has_table(conn, COMM_PARTICIPANTS):
        op.drop_table(COMM_PARTICIPANTS)
    if _has_table(conn, COMM_THREADS):
        op.drop_table(COMM_THREADS)
