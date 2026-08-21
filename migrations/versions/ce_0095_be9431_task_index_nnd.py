# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9431: restore ``NULLS NOT DISTINCT`` on ``uq_task_taxonomy_active`` (healing).

Revision ID: ce_0095_be9431_task_index_nnd
Revises: ce_0094_per_product_export_staleness
Create Date: 2026-08-14

WHAT WAS LOST. ``ce_0023`` created ``uq_task_taxonomy_active`` in raw SQL WITH
``NULLS NOT DISTINCT``. ``ce_0059`` (BE-6130b) had to widen its predicate, and
rewrote the statement as ``op.create_index(...)`` kwargs -- the flag had no
kwarg in the SQL being translated, so it was silently dropped.
``baseline_v38_unified.py`` was later derived from a migrated database and
inherited the weakened shape, so fresh installs got it too.

WHY THAT MATTERS. ``subseries`` is NULL on ordinary rows, and under Postgres'
default NULLS DISTINCT a NULL anywhere in the indexed tuple makes the row
unique by construction. So since ce_0059 this index has rejected nothing for
the common case: two live typed tasks in one product could share a serial.
Measured 2026-08-14 on two live databases -- pre-ce_0059 ``giljo_mcp`` still
has ``indnullsnotdistinct = true``, post-ce_0059 ``giljo_mcp_ce`` has false.
The row-locked serial allocator (``get_next_series_number_shared``) is still
doing the real work; what vanished is the backstop beneath it.

WHY THIS MIGRATION HEALS FIRST. A plain ``CREATE UNIQUE INDEX`` fails on any
database that already holds duplicates, and the CE installer reruns
``alembic upgrade`` on every boot -- so a naive migration would brick a
self-hoster's boot with no operator around to clean the database up. Healing is
therefore part of the migration, not a runbook step (CLAUDE.md's data-facing
DoD: "fix prod manually" is banned).

HEALING POLICY: REASSIGN, never delete. Within each colliding group the
earliest row keeps its serial; every other row is reassigned a fresh serial
above the bucket's watermark, which is ``MAX(series_number)`` across live
tasks AND projects for that ``(tenant_key, product_id)`` -- the same shared
line ``get_next_series_number_shared`` allocates from, and the same rule
``ce_0067`` used for the identical problem. Because that allocator is MAX-based
(there is no counter table), a serial handed out here can never collide with a
future mint. The title is the durable identity; a reassigned serial is a
renumbering, not a data loss. On a database whose bucket has already consumed
the whole 1-9999 space the reassignment can exceed that app-level cap, which is
tolerated on read -- refusing to boot would be the worse outcome, and such a
bucket is already at the allocator's exhaustion error.

IDEMPOTENT. The guard is the index's own ``pg_index.indnullsnotdistinct``:
once restored, every rerun (CE's every-boot upgrade, SaaS' ``upgrade heads``)
returns immediately. A fresh install reaches this revision with the baseline's
already-strict index and no rows, so it is a pure no-op there too.

Edition Scope: Both (``tasks`` is a CE core table; SaaS runs the CE chain).
"""

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
    """``True``/``False`` for the live index, ``None`` when it does not exist."""
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
    """Highest live serial across BOTH tables in the bucket (0 if none).

    Mirrors ``ce_0067._watermark`` and ``get_next_series_number_shared``: tasks
    and projects share one serial line per ``(tenant_key, product_id)``, and
    soft-deleted rows are excluded from the high-water mark.
    """
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
    """Reassign serials until the strict index can be built. Returns the count.

    ``GROUP BY`` already compares with ``IS NOT DISTINCT FROM`` semantics, which
    is exactly what ``NULLS NOT DISTINCT`` will enforce -- so this detector and
    the index agree by construction rather than by a hand-written NULL dance.
    """
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

        # Earliest row keeps the serial. created_at is nullable, and Postgres
        # sorts NULLs last on ASC, so a row with no timestamp is treated as the
        # newest -- deterministic, and the tie-break on id keeps it stable.
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
        return  # already strict -- CE reruns this on every boot

    # Hold the same lock CREATE INDEX will take, but take it BEFORE healing.
    # Without this there is a window between the last UPDATE and the CREATE in
    # which a still-running old process could insert a fresh duplicate, and the
    # CREATE would then fail -- turning a healing migration back into the boot
    # breaker it exists to prevent. SHARE is the level CREATE INDEX uses anyway,
    # so this widens the existing lock rather than adding a new kind of one.
    op.execute("LOCK TABLE tasks IN SHARE MODE")

    # Say it out loud when it happens: this renumbers a user's tasks, and a
    # silent renumber is exactly the kind of thing an operator should not have to
    # discover from the UI. Quiet on the overwhelmingly common zero case.
    healed = _heal_duplicates(conn)
    if healed:
        print(f"ce_0095: reassigned {healed} duplicate task serial(s) before restoring the unique index")  # noqa: T201

    # Raw SQL on purpose. Expressing this as op.create_index(...) kwargs is
    # precisely how ce_0059 lost the property in the first place; the statement
    # below says what it builds.
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(
        f"CREATE UNIQUE INDEX {_INDEX} ON public.tasks USING btree ({_COLUMNS}) NULLS NOT DISTINCT WHERE ({_PREDICATE})"
    )


def downgrade() -> None:
    conn = op.get_bind()

    if _nulls_not_distinct(conn) is not True:
        return

    # Schema only. The reassigned serials are valid data and their original
    # slots may since have been reused, so they are not reverted -- same
    # one-way stance as ce_0067 and ce_0023's serial backfill.
    op.execute(f"DROP INDEX IF EXISTS {_INDEX}")
    op.execute(f"CREATE UNIQUE INDEX {_INDEX} ON public.tasks USING btree ({_COLUMNS}) WHERE ({_PREDICATE})")
