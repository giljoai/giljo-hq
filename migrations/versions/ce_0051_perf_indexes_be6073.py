# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0051_perf_indexes_be6073"
down_revision = "ce_0050_roadmap_sort_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_tenant_from_agent_created "
        "ON messages (tenant_key, from_agent_id, created_at)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_executions_tenant_job_started "
        "ON agent_executions (tenant_key, job_id, started_at DESC)"
    )
    op.execute("CREATE INDEX IF NOT EXISTS idx_message_recipients_tenant ON message_recipients (tenant_key)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_message_acks_tenant ON message_acknowledgments (tenant_key)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_message_completions_tenant ON message_completions (tenant_key)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_message_completions_tenant")
    op.execute("DROP INDEX IF EXISTS idx_message_acks_tenant")
    op.execute("DROP INDEX IF EXISTS idx_message_recipients_tenant")
    op.execute("DROP INDEX IF EXISTS idx_agent_executions_tenant_job_started")
    op.execute("DROP INDEX IF EXISTS idx_messages_tenant_from_agent_created")
