# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0044_antigravity_tool_type"
down_revision = "ce_0043_projects_execution_mode_nullable"
branch_labels = None
depends_on = None


_TOOL_TYPE_CONSTRAINT = "ck_agent_execution_tool_type"

_TOOL_TYPE_CHECK_OLD = "tool_type IN ('claude-code', 'codex', 'gemini', 'universal')"
_TOOL_TYPE_CHECK_NEW = "tool_type IN ('claude-code', 'codex', 'gemini', 'antigravity', 'universal')"


def _has_check_constraint(conn, name: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE constraint_name = :name AND constraint_type = 'CHECK'"
        ),
        {"name": name},
    )
    return result.first() is not None


def upgrade() -> None:
    conn = op.get_bind()

    if _has_check_constraint(conn, _TOOL_TYPE_CONSTRAINT):
        op.drop_constraint(_TOOL_TYPE_CONSTRAINT, "agent_executions", type_="check")
    op.create_check_constraint(
        _TOOL_TYPE_CONSTRAINT,
        "agent_executions",
        _TOOL_TYPE_CHECK_NEW,
    )


def downgrade() -> None:
    conn = op.get_bind()

    if _has_check_constraint(conn, _TOOL_TYPE_CONSTRAINT):
        op.drop_constraint(_TOOL_TYPE_CONSTRAINT, "agent_executions", type_="check")
    op.create_check_constraint(
        _TOOL_TYPE_CONSTRAINT,
        "agent_executions",
        _TOOL_TYPE_CHECK_OLD,
    )
