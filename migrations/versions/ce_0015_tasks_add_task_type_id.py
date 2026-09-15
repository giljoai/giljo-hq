# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0015_tasks_add_task_type_id"
down_revision = "ce_0014_rename_project_types_to_taxonomy_types"
branch_labels = None
depends_on = None


TASKS_TABLE = "tasks"
NEW_COL = "task_type_id"
NEW_FK = "tasks_task_type_id_fkey"
NEW_IDX = "idx_task_task_type_id"


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


def _has_index(conn, index: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :index"),
        {"index": index},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, TASKS_TABLE, NEW_COL):
        op.add_column(
            TASKS_TABLE,
            sa.Column(NEW_COL, sa.String(36), nullable=True),
        )

    if not _has_constraint(conn, TASKS_TABLE, NEW_FK):
        op.create_foreign_key(
            NEW_FK,
            TASKS_TABLE,
            "taxonomy_types",
            [NEW_COL],
            ["id"],
            ondelete="SET NULL",
        )

    if not _has_index(conn, NEW_IDX):
        op.create_index(NEW_IDX, TASKS_TABLE, [NEW_COL])

    if _has_column(conn, TASKS_TABLE, "category"):
        conn.execute(
            sa.text(
                """
                UPDATE tasks t
                SET task_type_id = tt.id
                FROM taxonomy_types tt
                WHERE t.task_type_id IS NULL
                  AND t.category IS NOT NULL
                  AND t.tenant_key = tt.tenant_key
                  AND UPPER(t.category) = UPPER(tt.abbreviation)
                """
            )
        )
        conn.execute(
            sa.text(
                """
                UPDATE tasks t
                SET task_type_id = tt.id
                FROM taxonomy_types tt
                WHERE t.task_type_id IS NULL
                  AND t.category IS NOT NULL
                  AND t.tenant_key = tt.tenant_key
                  AND LOWER(t.category) = LOWER(tt.label)
                """
            )
        )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_index(conn, NEW_IDX):
        op.drop_index(NEW_IDX, table_name=TASKS_TABLE)

    if _has_constraint(conn, TASKS_TABLE, NEW_FK):
        op.drop_constraint(NEW_FK, TASKS_TABLE, type_="foreignkey")

    if _has_column(conn, TASKS_TABLE, NEW_COL):
        op.drop_column(TASKS_TABLE, NEW_COL)
