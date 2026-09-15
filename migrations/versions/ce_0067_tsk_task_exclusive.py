# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import text


revision = "ce_0067_tsk_task_exclusive"
down_revision = "ce_0066_users_token_revocation_epoch"
branch_labels = None
depends_on = None


_TSK_ABBR = "TSK"
_TSK_LABEL = "Task"
_TSK_COLOR = "#8b5cf6"
_TSK_SORT_ORDER = 100


def _ensure_tsk_rows(conn) -> None:
    conn.execute(
        text(
            """
            INSERT INTO taxonomy_types
                (id, tenant_key, abbreviation, label, color, sort_order, created_at, updated_at)
            SELECT
                gen_random_uuid()::text, t.tenant_key, :abbr, :label, :color, :sort_order,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM (SELECT DISTINCT tenant_key FROM taxonomy_types) t
            WHERE NOT EXISTS (
                SELECT 1 FROM taxonomy_types x
                WHERE x.tenant_key = t.tenant_key AND x.abbreviation = :abbr
            )
            """
        ).bindparams(abbr=_TSK_ABBR, label=_TSK_LABEL, color=_TSK_COLOR, sort_order=_TSK_SORT_ORDER)
    )


def _buckets(conn):
    return conn.execute(
        text(
            """
            SELECT DISTINCT tenant_key, product_id FROM tasks
            UNION
            SELECT DISTINCT tenant_key, product_id FROM projects
            """
        )
    ).fetchall()


def _watermark(conn, tk, pid) -> int:
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
        {"tk": tk, "pid": pid},
    ).scalar_one()


def upgrade() -> None:
    conn = op.get_bind()
    _ensure_tsk_rows(conn)

    for tk, pid in _buckets(conn):
        tsk_id = conn.execute(
            text("SELECT id FROM taxonomy_types WHERE tenant_key = :tk AND abbreviation = :abbr").bindparams(
                tk=tk, abbr=_TSK_ABBR
            )
        ).scalar_one_or_none()
        if tsk_id is None:
            continue

        watermark = _watermark(conn, tk, pid)

        claimed = {
            (r.series_number, r.subseries)
            for r in conn.execute(
                text(
                    """
                    SELECT series_number, subseries FROM tasks
                    WHERE tenant_key = :tk AND product_id IS NOT DISTINCT FROM :pid
                      AND task_type_id = :tsk AND deleted_at IS NULL
                      AND series_number IS NOT NULL
                    """
                ),
                {"tk": tk, "pid": pid, "tsk": tsk_id},
            )
        }
        rows = conn.execute(
            text(
                """
                SELECT id, series_number, subseries FROM tasks
                WHERE tenant_key = :tk AND product_id IS NOT DISTINCT FROM :pid
                  AND task_type_id IS DISTINCT FROM :tsk AND deleted_at IS NULL
                ORDER BY (series_number IS NULL), series_number, subseries, id
                """
            ),
            {"tk": tk, "pid": pid, "tsk": tsk_id},
        ).fetchall()
        for row in rows:
            series, subseries = row.series_number, row.subseries
            if series is None or (series, subseries) in claimed:
                watermark += 1
                series, subseries = watermark, None
            claimed.add((series, subseries))
            conn.execute(
                text("UPDATE tasks SET task_type_id = :tsk, series_number = :s, subseries = :sub WHERE id = :id"),
                {"tsk": tsk_id, "s": series, "sub": subseries, "id": row.id},
            )

        claimed_proj = {
            (r.series_number, r.subseries)
            for r in conn.execute(
                text(
                    """
                    SELECT series_number, subseries FROM projects
                    WHERE tenant_key = :tk AND product_id IS NOT DISTINCT FROM :pid
                      AND project_type_id IS NULL AND deleted_at IS NULL
                      AND series_number IS NOT NULL
                    """
                ),
                {"tk": tk, "pid": pid},
            )
        }
        proj_rows = conn.execute(
            text(
                """
                SELECT id, series_number, subseries FROM projects
                WHERE tenant_key = :tk AND product_id IS NOT DISTINCT FROM :pid
                  AND project_type_id = :tsk AND deleted_at IS NULL
                ORDER BY (series_number IS NULL), series_number, subseries, id
                """
            ),
            {"tk": tk, "pid": pid, "tsk": tsk_id},
        ).fetchall()
        for row in proj_rows:
            series, subseries = row.series_number, row.subseries
            if series is not None and (series, subseries) in claimed_proj:
                watermark += 1
                series, subseries = watermark, None
            if series is not None:
                claimed_proj.add((series, subseries))
            conn.execute(
                text("UPDATE projects SET project_type_id = NULL, series_number = :s, subseries = :sub WHERE id = :id"),
                {"s": series, "sub": subseries, "id": row.id},
            )


def downgrade() -> None:
    pass
