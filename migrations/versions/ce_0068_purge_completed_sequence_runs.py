# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op
from sqlalchemy import text


revision = "ce_0068_purge_completed_sequence_runs"
down_revision = "ce_0067_tsk_task_exclusive"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        text(
            """
            DELETE FROM agent_executions ae
            USING agent_jobs aj, sequence_runs sr
            WHERE ae.job_id = aj.job_id
              AND ae.tenant_key = aj.tenant_key
              AND aj.tenant_key = sr.tenant_key
              AND aj.project_id IS NULL
              AND aj.job_metadata->>'run_id' = sr.id
              AND sr.status = 'completed'
            """
        )
    )

    op.execute(
        text(
            """
            DELETE FROM agent_jobs aj
            USING sequence_runs sr
            WHERE aj.tenant_key = sr.tenant_key
              AND aj.project_id IS NULL
              AND aj.job_metadata->>'run_id' = sr.id
              AND sr.status = 'completed'
            """
        )
    )

    op.execute(text("DELETE FROM sequence_runs WHERE status = 'completed'"))


def downgrade() -> None:
    pass
