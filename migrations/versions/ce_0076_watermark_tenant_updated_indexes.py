# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from alembic import op


revision = "ce_0076_watermark_tenant_updated_indexes"
down_revision = "ce_0075_projects_ever_launched_at"
branch_labels = None
depends_on = None


_TABLES = (
    "agent_templates",
    "agent_todo_items",
    "comm_threads",
    "configurations",
    "organizations",
    "product_agent_assignments",
    "product_architectures",
    "product_memory_entries",
    "product_tech_stacks",
    "product_test_configs",
    "products",
    "projects",
    "roadmap_items",
    "roadmaps",
    "sequence_runs",
    "settings",
    "setup_state",
    "taxonomy_types",
    "tenant_skills_ack",
    "user_field_priorities",
    "vision_documents",
)


def _index_name(table: str) -> str:
    return f"idx_{table}_tenant_updated"


def upgrade() -> None:
    for table in _TABLES:
        op.execute(f"CREATE INDEX IF NOT EXISTS {_index_name(table)} ON {table} (tenant_key, updated_at)")


def downgrade() -> None:
    for table in reversed(_TABLES):
        op.execute(f"DROP INDEX IF EXISTS {_index_name(table)}")
