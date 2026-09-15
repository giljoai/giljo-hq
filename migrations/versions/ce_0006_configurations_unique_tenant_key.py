# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0006_configurations_unique_tenant_key"
down_revision = "ce_0005_drop_users_execution_mode"
branch_labels = None
depends_on = None


CONSTRAINT_NAME = "uq_config_tenant_key"
TABLE_NAME = "configurations"
ORCHESTRATOR_PROMPT_KEY = "system.orchestrator_prompt"


def _has_constraint(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :constraint"
        ),
        {"table": table, "constraint": constraint},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text("DELETE FROM configurations WHERE tenant_key IS NULL AND key = :key"),
        {"key": ORCHESTRATOR_PROMPT_KEY},
    )

    if not _has_constraint(conn, TABLE_NAME, CONSTRAINT_NAME):
        op.create_unique_constraint(
            CONSTRAINT_NAME,
            TABLE_NAME,
            ["tenant_key", "key"],
        )


def downgrade() -> None:
    conn = op.get_bind()
    if _has_constraint(conn, TABLE_NAME, CONSTRAINT_NAME):
        op.drop_constraint(CONSTRAINT_NAME, TABLE_NAME, type_="unique")
