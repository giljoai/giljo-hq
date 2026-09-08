# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Add tasks.deleted_at + vision_documents.deleted_at (trash/recover) — BE-6130b.

Revision ID: ce_0059_softdelete_recover_be6130b
Revises: ce_0058_sequence_runs
Create Date: 2026-06-18

Extends the Project/Product soft-delete (trash/recover) pattern to two top gap
entities from the BE-6130a audit:

* ``tasks.deleted_at``           — soft-delete for the user ``DELETE /tasks/{id}``.
* ``vision_documents.deleted_at`` — soft-delete for ``DELETE /vision-documents/{id}``
  (its MCPContextIndex chunks ride the parent: they survive the soft-delete and
  are filtered from retrieval until the doc is restored).

(``comm_threads.deleted_at`` already shipped in ce_0057 and is NOT touched here.
``agent_templates`` is deferred to a tracked follow-up.)

Two existing UNIQUE guards are made partial so a serial / document name frees up
when its row is trashed and can be re-minted on a later create or restore:

* ``uq_task_taxonomy_active``     — add ``AND deleted_at IS NULL`` to its predicate.
* ``uq_vision_doc_product_name``  — convert the plain UNIQUE CONSTRAINT to a
  partial UNIQUE INDEX with ``WHERE deleted_at IS NULL``.

Idempotent (existence / predicate guards) because the CE installer reruns
migrations on every boot. Reversible. No backfill — existing rows default to NULL
(live), the correct pre-feature state, so old-shape rows are tolerated unchanged.
"""

import sqlalchemy as sa
from alembic import op


# Chains after ce_0058_sequence_runs (BE-6131a) so the CE chain stays linear:
# ce_0057_comm_thread_soft_delete -> ce_0058_sequence_runs -> ce_0059.
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
    """True if the index exists AND its definition mentions ``needle`` (e.g. a
    column added to a partial predicate). Used to make the index conversions
    idempotent — once converted the new predicate is present, so reruns skip."""
    indexdef = conn.execute(
        sa.text("SELECT indexdef FROM pg_indexes WHERE indexname = :i"),
        {"i": index},
    ).scalar()
    return bool(indexdef) and needle in indexdef


def upgrade() -> None:
    conn = op.get_bind()

    # --- 1. tasks.deleted_at --------------------------------------------------
    if not _column_exists(conn, "tasks", "deleted_at"):
        op.add_column("tasks", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # uq_task_taxonomy_active: add deleted_at to the partial predicate so a
    # trashed task's serial can be re-minted without a unique clash.
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

    # --- 2. vision_documents.deleted_at --------------------------------------
    if not _column_exists(conn, "vision_documents", "deleted_at"):
        op.add_column("vision_documents", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # uq_vision_doc_product_name: plain UNIQUE CONSTRAINT -> partial UNIQUE INDEX
    # (live rows only) so a doc name can be reused after the prior doc is trashed.
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

    # Revert vision_documents partial unique index -> plain unique constraint.
    if _index_def_contains(conn, "uq_vision_doc_product_name", "deleted_at"):
        op.execute("DROP INDEX IF EXISTS uq_vision_doc_product_name")
        op.create_unique_constraint("uq_vision_doc_product_name", "vision_documents", ["product_id", "document_name"])
    if _index_exists(conn, "idx_vision_doc_deleted_at"):
        op.drop_index("idx_vision_doc_deleted_at", table_name="vision_documents")
    if _column_exists(conn, "vision_documents", "deleted_at"):
        op.drop_column("vision_documents", "deleted_at")

    # Revert tasks partial unique index predicate (drop deleted_at clause).
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
