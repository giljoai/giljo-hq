# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""IMP-6262: make the reserved ``TSK`` tag task-exclusive.

Revision ID: ce_0067_tsk_task_exclusive
Revises: ce_0066_users_token_revocation_epoch
Create Date: 2026-07-01

Tasks and projects share one alias-prefix namespace (BE/FE/INF/SEC/DOC...) and
one serial line, so an alias alone cannot tell a task from a project. Only
``TSK-`` is meant to be task-exclusive, but two legacy shapes break that:

  1. LEGACY TASKS created before BE-6049c still carry project-style types
     (``BE-6080``, ``INF-6044`` are tasks) — indistinguishable from projects.
  2. Past task->project CONVERSIONS copied the task's type onto the project;
     once tasks are TSK-only that mints ``TSK``-typed PROJECTS.

This backfill closes both so the rule ``TSK-nnnn = task; everything else =
project`` holds structurally (the conversion path is fixed in the same change to
strip the type going forward — task_conversion_service.py):

  Step 0. Ensure every tenant that owns taxonomy has the reserved ``TSK`` row
          (lazy-seed parity with ensure_reserved_task_type / ce_0054's CHT
          backfill), so re-typing always has a target.
  Step A. Re-type every non-TSK live task -> ``TSK``.
  Step B. Un-type every ``TSK``-typed live project -> NULL (untyped; the user
          re-tags it later).

Both A and B are COLLISION-SAFE. ce_0023 backfilled serials PER TYPE, so legacy
rows of different types can share a serial (e.g. ``DOC-19`` + ``BE-19`` tasks).
Collapsing them onto one namespace can violate the partial-unique indexes
``uq_task_taxonomy_active`` / ``uq_project_taxonomy_active`` (live + numbered
rows only). BE-9431 correction: this text originally said "both NULLS NOT
DISTINCT", which was true of ``uq_project_taxonomy_active`` but not of the task
index at the time this revision runs — ce_0059 had dropped that flag and
ce_0095 only restores it later in the chain. The collision handling below is
therefore stricter than the task index required in that window, which is safe
(it avoids collisions the index would not have caught) and is exactly what the
restored index now enforces. Where a re-typed/un-typed row would collide
with a slot already claimed in its destination namespace, we reassign it a fresh
serial above the bucket's global (tasks + projects) watermark — this design drops
the historical serial (title is the durable identity). Rows that do NOT
collide keep their original serial.

Idempotent: a second run finds no non-TSK tasks and no TSK-typed projects, so
both steps are clean no-ops. Existence-guarded throughout — a fresh install has
no legacy rows and this is a no-op.

Edition Scope: CE (``tasks`` / ``projects`` / ``taxonomy_types`` are CE core
tables; startup runs ``alembic upgrade head`` on the CE chain, SaaS inherits).
Data-only — no schema change, no schema-drift impact.
"""

from alembic import op
from sqlalchemy import text


revision = "ce_0067_tsk_task_exclusive"
down_revision = "ce_0066_users_token_revocation_epoch"
branch_labels = None
depends_on = None


# Keep in sync with taxonomy_ops.RESERVED_TASK_TYPE_ABBR + the
# DEFAULT_TAXONOMY_TYPES "Task" entry (purple).
_TSK_ABBR = "TSK"
_TSK_LABEL = "Task"
_TSK_COLOR = "#8b5cf6"
_TSK_SORT_ORDER = 100


def _ensure_tsk_rows(conn) -> None:
    """Step 0: seed the reserved TSK taxonomy row for every tenant that has any
    taxonomy types but lacks TSK (idempotent via NOT EXISTS; safe vs
    uq_taxonomy_type_abbr)."""
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
    """Distinct (tenant_key, product_id) pairs across tasks and projects."""
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
    """Highest live serial across BOTH tables in the bucket (0 if none)."""
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
            # Tenant owns rows in this product but has no taxonomy types at all
            # (so _ensure_tsk_rows skipped it). Nothing typed to reconcile here.
            continue

        watermark = _watermark(conn, tk, pid)

        # ---- Step A: re-type non-TSK live tasks -> TSK (collision-safe) ----
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

        # ---- Step B: un-type TSK-typed live projects -> NULL (collision-safe) ----
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
    # Not reversed: the re-typed tasks and un-typed projects are valid data, and
    # the original per-type serial slots may since have been reused. Reverting
    # would risk NULLS-NOT-DISTINCT collisions. This mirrors ce_0023's one-way
    # serial backfill. (No-op downgrade so the chain stays walkable.)
    pass
