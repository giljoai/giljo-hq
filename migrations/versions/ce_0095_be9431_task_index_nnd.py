# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import text


revision = "ce_0095_be9431_task_index_nnd"
down_revision = "ce_0094_per_product_export_staleness"
branch_labels = None
depends_on = None


_INDEX = "uq_task_taxonomy_active"
_COLUMNS = "tenant_key, product_id, task_type_id, series_number, subseries"
_PREDICATE = "series_number IS NOT NULL AND deleted_at IS NULL"


def _nulls_not_distinct(conn) -> bool | None:
    return conn.execute(
        text(
            """
            SELECT i.indnullsnotdistinct
            FROM pg_index i
            JOIN pg_class c ON c.oid = i.indexrelid
            JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' AND c.relname = :i
            """
        ),
        {"i": _INDEX},
    ).scalar()


def _watermark(conn, tenant_key, product_id) -> int:
    return conn.execute(
        text(
            """
            SELECT GREATEST(
                COALESCE((SELECT MAX(series_number) FROM tasks
                          WHERE tenant_key = :tk AND product_id IS NOT DISTINCT FROM :pid
                            AND deleted_at IS NULL), 0),
                COALESCE((SELECT MAX(series_number) FROM projects
                          WHERE tenant_key = :tk AND product_id IS NOT DISTINCT FROM :pid
                            AND deleted_at IS NULL), 0)
            )
            """
        ),
        {"tk": tenant_key, "pid": product_id},
    ).scalar_one()


def _heal_duplicates(conn) -> int:
    groups = conn.execute(
        text(
            f"""
            SELECT tenant_key, product_id, task_type_id, series_number, subseries
            FROM tasks
            WHERE {_PREDICATE}
            GROUP BY tenant_key, product_id, task_type_id, series_number, subseries
            HAVING COUNT(*) > 1
            """
        )
    ).fetchall()

    watermarks: dict[tuple, int] = {}
    reassigned = 0
    for group in groups:
        bucket = (group.tenant_key, group.product_id)
        if bucket not in watermarks:
            watermarks[bucket] = _watermark(conn, *bucket)

        rows = conn.execute(
            text(
                f"""
                SELECT id FROM tasks
                WHERE tenant_key = :tk
                  AND product_id IS NOT DISTINCT FROM :pid
                  AND task_type_id IS NOT DISTINCT FROM :ttid
                  AND series_number = :sn
                  AND subseries IS NOT DISTINCT FROM :sub
                  AND {_PREDICATE}
                ORDER BY created_at, id
                """
            ),
            {
                "tk": group.tenant_key,
                "pid": group.product_id,
                "ttid": group.task_type_id,
                "sn": group.series_number,
                "sub": group.subseries,
            },
        ).fetchall()

        for row in rows[1:]:
            watermarks[bucket] += 1
            conn.execute(
                text("UPDATE tasks SET series_number = :s, subseries = NULL WHERE id = :id"),
                {"s": watermarks[bucket], "id": row.id},
            )
            reassigned += 1

    return reassigned


def upgrade() -> None:
    conn = op.get_bind()

    if _nulls_not_distinct(conn) is True:
        return

    op.execute("LOCK TABLE tasks IN SHARE MODE")

    healed = _heal_duplicates(conn)
    if healed:
        print(f"ce_0095: reassigned {healed} duplicate task serial(s) before restoring the unique index")  # noqa: T201

    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} ON public.tasks USING btree ({_COLUMNS}) NULLS NOT DISTINCT WHERE ({_PREDICATE})"
    )


def downgrade() -> None:
    conn = op.get_bind()

    if _nulls_not_distinct(conn) is not True:
        return

    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"CREATE UNIQUE INDEX {_INDEX} ON public.tasks USING btree ({_COLUMNS}) WHERE ({_PREDICATE})")
