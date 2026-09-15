# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0046_list_tables_tenant_created_index"
down_revision = "ce_0045_pme_tenant_timestamp_index"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_projects_tenant_created "
        "ON projects (tenant_key, created_at DESC) "
        "WHERE deleted_at IS NULL"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_messages_tenant_created "
        "ON messages (tenant_key, created_at DESC)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS idx_agent_jobs_tenant_created "
        "ON agent_jobs (tenant_key, created_at DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS idx_agent_jobs_tenant_created")
    op.execute("DROP INDEX IF EXISTS idx_messages_tenant_created")
    op.execute("DROP INDEX IF EXISTS idx_projects_tenant_created")
