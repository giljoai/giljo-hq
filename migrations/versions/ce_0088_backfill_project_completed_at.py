# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

import sqlalchemy as sa
from alembic import op


revision = "ce_0088_backfill_project_completed_at"
down_revision = "ce_0087_comm_threads_sequence_run_fk"
branch_labels = None
depends_on = None

logger = logging.getLogger("alembic.runtime.migration")

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
    pass
