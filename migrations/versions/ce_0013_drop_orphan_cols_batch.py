# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import TSVECTOR


revision = "ce_0013_drop_orphan_cols_batch"
down_revision = "ce_0012_drop_setup_state_orphan_cols"
branch_labels = None
depends_on = None


MESSAGES_COLS = (
    "processing_started_at",
    "retry_count",
    "max_retries",
    "backoff_seconds",
    "circuit_breaker_status",
)
TEMPLATES_COLS = ("last_used_at", "usage_count")
CONTEXT_INDEXES = ("idx_mcp_context_searchable", "idx_mcp_context_chunk_id")
CONTEXT_COLS = ("searchable_vector", "chunk_id")
APIKEY_INDEXES = ("idx_api_key_ip_log_last_seen",)
APIKEY_COLS = ("first_seen_at", "last_seen_at")
CONFIG_COLS = ("is_secret",)


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
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

    for col in MESSAGES_COLS:
        if _has_column(conn, "messages", col):
            op.drop_column("messages", col)

    for col in TEMPLATES_COLS:
        if _has_column(conn, "agent_templates", col):
            op.drop_column("agent_templates", col)

    for index in CONTEXT_INDEXES:
        if _has_index(conn, index):
            op.drop_index(index, table_name="mcp_context_index")
    for col in CONTEXT_COLS:
        if _has_column(conn, "mcp_context_index", col):
            op.drop_column("mcp_context_index", col)

    for index in APIKEY_INDEXES:
        if _has_index(conn, index):
            op.drop_index(index, table_name="api_key_ip_log")
    for col in APIKEY_COLS:
        if _has_column(conn, "api_key_ip_log", col):
            op.drop_column("api_key_ip_log", col)

    for col in CONFIG_COLS:
        if _has_column(conn, "configurations", col):
            op.drop_column("configurations", col)


def downgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, "configurations", "is_secret"):
        op.add_column(
            "configurations",
            sa.Column("is_secret", sa.Boolean(), nullable=True, server_default=sa.text("false")),
        )

    if not _has_column(conn, "api_key_ip_log", "first_seen_at"):
        op.add_column(
            "api_key_ip_log",
            sa.Column(
                "first_seen_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
    if not _has_column(conn, "api_key_ip_log", "last_seen_at"):
        op.add_column(
            "api_key_ip_log",
            sa.Column(
                "last_seen_at",
                sa.DateTime(timezone=True),
                nullable=False,
                server_default=sa.text("now()"),
            ),
        )
    if not _has_index(conn, "idx_api_key_ip_log_last_seen"):
        op.create_index("idx_api_key_ip_log_last_seen", "api_key_ip_log", ["last_seen_at"])

    if not _has_column(conn, "mcp_context_index", "chunk_id"):
        op.add_column("mcp_context_index", sa.Column("chunk_id", sa.String(length=36), nullable=True))
    if not _has_column(conn, "mcp_context_index", "searchable_vector"):
        op.add_column("mcp_context_index", sa.Column("searchable_vector", TSVECTOR(), nullable=True))
    if not _has_index(conn, "idx_mcp_context_chunk_id"):
        op.create_index("idx_mcp_context_chunk_id", "mcp_context_index", ["chunk_id"])
    if not _has_index(conn, "idx_mcp_context_searchable"):
        op.create_index(
            "idx_mcp_context_searchable",
            "mcp_context_index",
            ["searchable_vector"],
            postgresql_using="gin",
        )

    if not _has_column(conn, "agent_templates", "last_used_at"):
        op.add_column(
            "agent_templates",
            sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        )
    if not _has_column(conn, "agent_templates", "usage_count"):
        op.add_column(
            "agent_templates",
            sa.Column("usage_count", sa.Integer(), nullable=True, server_default=sa.text("0")),
        )

    if not _has_column(conn, "messages", "processing_started_at"):
        op.add_column("messages", sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True))
    if not _has_column(conn, "messages", "retry_count"):
        op.add_column("messages", sa.Column("retry_count", sa.Integer(), nullable=True, server_default=sa.text("0")))
    if not _has_column(conn, "messages", "max_retries"):
        op.add_column("messages", sa.Column("max_retries", sa.Integer(), nullable=True, server_default=sa.text("3")))
    if not _has_column(conn, "messages", "backoff_seconds"):
        op.add_column(
            "messages",
            sa.Column("backoff_seconds", sa.Integer(), nullable=True, server_default=sa.text("60")),
        )
    if not _has_column(conn, "messages", "circuit_breaker_status"):
        op.add_column("messages", sa.Column("circuit_breaker_status", sa.String(length=20), nullable=True))
