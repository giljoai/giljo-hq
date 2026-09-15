# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0023_tasks_shared_taxonomy_serial"
down_revision = "ce_0022_oauth_revoked_tokens"
branch_labels = None
depends_on = None


TASK_INDEX = "uq_task_taxonomy_active"


def _has_index(conn, indexname: str) -> bool:
    return (
        conn.execute(
            sa.text("SELECT 1 FROM pg_indexes WHERE indexname = :name"),
            {"name": indexname},
        ).first()
        is not None
    )


def upgrade() -> None:
    conn = op.get_bind()

    buckets = conn.execute(
        sa.text(
            """
            SELECT DISTINCT tenant_key, product_id, task_type_id
            FROM tasks
            WHERE task_type_id IS NOT NULL AND series_number IS NULL
            """
        )
    ).fetchall()

    for tenant_key, product_id, task_type_id in buckets:
        max_existing = conn.execute(
            sa.text(
                """
                SELECT GREATEST(
                    COALESCE((
                        SELECT MAX(series_number) FROM tasks
                        WHERE tenant_key = :tk AND product_id = :pid
                          AND task_type_id = :ttid
                    ), 0),
                    COALESCE((
                        SELECT MAX(series_number) FROM projects
                        WHERE tenant_key = :tk AND product_id = :pid
                          AND project_type_id = :ttid
                    ), 0)
                )
                """
            ),
            {"tk": tenant_key, "pid": product_id, "ttid": task_type_id},
        ).scalar_one()

        rows = conn.execute(
            sa.text(
                """
                SELECT id FROM tasks
                WHERE tenant_key = :tk AND product_id = :pid
                  AND task_type_id = :ttid AND series_number IS NULL
                ORDER BY created_at ASC, id ASC
                """
            ),
            {"tk": tenant_key, "pid": product_id, "ttid": task_type_id},
        ).fetchall()

        next_n = max_existing + 1
        for (task_id,) in rows:
            conn.execute(
                sa.text("UPDATE tasks SET series_number = :n WHERE id = :id"),
                {"n": next_n, "id": task_id},
            )
            next_n += 1

    if not _has_index(conn, TASK_INDEX):
        op.execute(
            sa.text(
                "CREATE UNIQUE INDEX uq_task_taxonomy_active "
                "ON tasks (tenant_key, product_id, task_type_id, series_number, subseries) "
                "NULLS NOT DISTINCT "
                "WHERE series_number IS NOT NULL"
            )
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_index(conn, TASK_INDEX):
        op.execute(sa.text(f"DROP INDEX {TASK_INDEX}"))
