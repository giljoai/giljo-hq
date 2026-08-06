# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9343: backfill ``projects.completed_at`` for rows already in a terminal status.

Revision ID: ce_0088_backfill_project_completed_at
Revises: ce_0087_comm_threads_sequence_run_fk
Create Date: 2026-08-02

``completed_at`` was written by SOME callers rather than guaranteed by the service
layer: ``update_project(status="completed")`` built its update dict from the
caller's fields alone, so a project closed through agent tooling landed as
``status=completed, closeout_executed_at=<ts>, completed_at=NULL``. Ten of ten
completed BE-93xx projects were measured NULL. BE-9343 fixes the write path; this
migration fixes the rows that path already produced.

Why a migration and not tolerance
---------------------------------
The Data-facing DoD offers two answers for existing rows: (a) code tolerates the
old shape, or (b) an idempotent migration rewrites it. Here (a) is precisely what
the dashboard was already doing -- ``ProjectsTable.vue`` rendered
``completed_at || updated_at`` under a column headed COMPLETED -- and that
tolerance is what produced the wrong date, because ANY later write (including the
hide/archive toggle) bumps ``updated_at``. So (b) it is.

The value is APPROXIMATE, and deliberately so
---------------------------------------------
``COALESCE(closeout_executed_at, updated_at)``:

  * ``closeout_executed_at`` is exact -- it is stamped at the moment the project
    was closed out, and never touched again.
  * ``updated_at`` is the fallback for rows that never ran a closeout, and it may
    have DRIFTED: it reflects the last write of any kind, not the completion.

An approximate date is strictly better than NULL for every consumer here -- the
sort orders correctly, ``completed_after`` / ``completed_before`` stop returning
nothing, and the Completed column shows a real column instead of a fallback. It is
not presented as exact anywhere, and no downstream code treats it as exact.

Idempotent
----------
``WHERE completed_at IS NULL`` is the guard: once a row is filled it no longer
matches, so the CE installer's every-boot ``alembic upgrade head`` re-run is a
clean no-op. Data-only -- both columns have existed since baseline_v37, so there
is no schema change to guard.

The status list is a FROZEN LITERAL, not an import
--------------------------------------------------
The runtime stamp (``_apply_project_updates``) keys on the live
``LIFECYCLE_FINISHED_STATUSES`` set, as it should. A migration must not: it has to
keep doing exactly what it did the day it was authored, even if that domain set
later gains or loses a member. These five values ARE that set as of this revision;
importing it would silently change what an already-applied historical migration
means. Both ``superseded`` (ce_0078) and ``parked`` (ce_0083) predate this
revision, so every enum label named below is guaranteed to exist. ``parked`` is
deliberately absent -- it is a resumable two-way door, not a finished state.

Edition Scope: Both -- ``projects`` is a CE table, so this lives in the CE chain
(``migrations/versions/``). SaaS inherits it unchanged on its next preDeploy
alembic run.
"""

import logging

import sqlalchemy as sa
from alembic import op


revision = "ce_0088_backfill_project_completed_at"
down_revision = "ce_0087_comm_threads_sequence_run_fk"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

# Frozen as of this revision -- see the module docstring for why this is a literal
# rather than an import of LIFECYCLE_FINISHED_STATUSES.
_TERMINAL_STATUSES = ("completed", "cancelled", "terminated", "deleted", "superseded")


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(
        sa.text(
            "UPDATE projects "
            "   SET completed_at = COALESCE(closeout_executed_at, updated_at) "
            " WHERE completed_at IS NULL "
            "   AND status IN :statuses "
            "   AND COALESCE(closeout_executed_at, updated_at) IS NOT NULL"
        ).bindparams(sa.bindparam("statuses", value=_TERMINAL_STATUSES, expanding=True))
    )
    logger.info("ce_0088: backfilled completed_at on %s terminal project row(s)", result.rowcount)


def downgrade() -> None:
    """Deliberate no-op -- this backfill is not reversible without destroying data.

    Nothing records WHICH rows were NULL before the upgrade ran, so a downgrade
    could only guess. The obvious heuristic -- NULL out any row whose
    ``completed_at`` equals ``COALESCE(closeout_executed_at, updated_at)`` -- would
    also clear rows the BE-9343 runtime stamp filled legitimately, because that
    stamp writes ``completed_at`` and ``updated_at`` from the same instant and the
    two therefore match exactly. Guessing would delete real completion dates.

    Leaving the backfilled values in place is safe in both directions: on older
    code ``completed_at`` is simply a populated nullable column, which every reader
    already handles (it was populated by the archive path long before this
    revision). So the correct downgrade is to do nothing, on purpose.
    """
