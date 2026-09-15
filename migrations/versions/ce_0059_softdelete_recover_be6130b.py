# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0059_softdelete_recover_be6130b"
down_revision = "ce_0058_sequence_runs"
branch_labels = None
depends_on = None


def _column_exists(conn, table: str, column: str) -> bool:
    return bool(
        conn.execute(
            sa.text(
                "SELECT EXISTS (SELECT FROM information_schema.columns WHERE table_name = :t AND column_name = :c)"
            ),
            {"t": table, "c": column},
        ).scalar()
    )


def _index_exists(conn, index: str) -> bool:
    return bool(
        conn.execute(
            sa.text("SELECT EXISTS (SELECT FROM pg_indexes WHERE indexname = :i)"),
            {"i": index},
        ).scalar()
    )


def _index_def_contains(conn, index: str, needle: str) -> bool:
    indexdef = conn.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :i"),
        {"i": index},
    ).scalar()
    return bool(indexdef) and needle in indexdef


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_exists(conn, "tasks", "deleted_at"):
        op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    if not _index_def_contains(conn, "uq_task_taxonomy_active", "deleted_at"):
        op.execute("DROP INDEX IF EXISTS uq_task_taxonomy_active")
        op.create_index(
            "uq_task_taxonomy_active",
            "tasks",
            ["tenant_key", "product_id", "task_type_id", "series_number", "subseries"],
            unique=True,
            postgresql_where=sa.text("series_number IS NOT NULL AND deleted_at IS NULL"),
        )

    if not _index_exists(conn, "idx_tasks_deleted_at"):
        op.create_index(
            "idx_tasks_deleted_at",
            "tasks",
            ["deleted_at"],
            postgresql_where=sa.text("deleted_at IS NOT NULL"),
        )

    if not _column_exists(conn, "vision_documents", "deleted_at"):
        op.add_column("vision_documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    if not _index_def_contains(conn, "uq_vision_doc_product_name", "deleted_at"):
        op.execute("ALTER TABLE vision_documents DROP CONSTRAINT IF EXISTS uq_vision_doc_product_name")
        op.execute("DROP INDEX IF EXISTS uq_vision_doc_product_name")
        op.create_index(
            "uq_vision_doc_product_name",
            "vision_documents",
            ["product_id", "document_name"],
            unique=True,
            postgresql_where=sa.text("deleted_at IS NULL"),
        )

    if not _index_exists(conn, "idx_vision_doc_deleted_at"):
        op.create_index(
            "idx_vision_doc_deleted_at",
            "vision_documents",
            ["deleted_at"],
            postgresql_where=sa.text("deleted_at IS NOT NULL"),
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _index_def_contains(conn, "uq_vision_doc_product_name", "deleted_at"):
        op.execute("DROP INDEX IF EXISTS uq_vision_doc_product_name")
        op.create_unique_constraint("uq_vision_doc_product_name", "vision_documents", ["product_id", "document_name"])
    if _index_exists(conn, "idx_vision_doc_deleted_at"):
        op.drop_index("idx_vision_doc_deleted_at", table_name="vision_documents")
    if _column_exists(conn, "vision_documents", "deleted_at"):
        op.drop_column("vision_documents", "deleted_at")

    if _index_def_contains(conn, "uq_task_taxonomy_active", "deleted_at"):
        op.execute("DROP INDEX IF EXISTS uq_task_taxonomy_active")
        op.create_index(
            "uq_task_taxonomy_active",
            "tasks",
            ["tenant_key", "product_id", "task_type_id", "series_number", "subseries"],
            unique=True,
            postgresql_where=sa.text("series_number IS NOT NULL"),
        )
    if _index_exists(conn, "idx_tasks_deleted_at"):
        op.drop_index("idx_tasks_deleted_at", table_name="tasks")
    if _column_exists(conn, "tasks", "deleted_at"):
        op.drop_column("tasks", "deleted_at")
