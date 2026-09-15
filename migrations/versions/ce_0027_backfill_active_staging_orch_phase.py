# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0027_backfill_active_staging_orch_phase"
down_revision = "ce_0026_agent_executions_add_project_phase"
branch_labels = None
depends_on = None


_BACKFILL_SQL = sa.text(
    """
    UPDATE agent_executions ae
    SET project_phase = 'staging'
    FROM agent_jobs aj
    JOIN projects p ON aj.project_id = p.id
    WHERE ae.job_id = aj.job_id
      AND ae.agent_display_name = 'orchestrator'
      AND ae.status NOT IN ('complete', 'closed', 'decommissioned')
      AND ae.project_phase != 'staging'
      AND (p.staging_status IS NULL OR p.staging_status IN ('staging', 'staged'))
    """
)


def upgrade() -> None:
    conn = op.get_bind()
    result = conn.execute(_BACKFILL_SQL)
    op.execute(
        sa.text(
            "DO $$ BEGIN RAISE NOTICE "
            "'[CE-0027] Backfilled % active staging orchestrator execution(s) "
            "to project_phase=staging', "
            f"{result.rowcount}; END $$"
        )
    )


def downgrade() -> None:
    pass
