# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0026_agent_executions_add_project_phase"
down_revision = "ce_0025_export_extend_download_type_allowlist"
branch_labels = None
depends_on = None


TABLE = "agent_executions"
COLUMN = "project_phase"
CONSTRAINT = "ck_agent_execution_project_phase"
ALLOWED_VALUES = ("staging", "implementation")


def _has_column(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text("SELECT 1 FROM information_schema.columns WHERE table_name = :table AND column_name = :column"),
        {"table": table, "column": column},
    )
    return result.first() is not None


def _has_constraint(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :constraint"
        ),
        {"table": table, "constraint": constraint},
    )
    return result.first() is not None


def _check_clause() -> str:
    rendered = ", ".join(f"'{v}'" for v in ALLOWED_VALUES)
    return f"{COLUMN} IN ({rendered})"


def upgrade() -> None:
    conn = op.get_bind()

    if not _has_column(conn, TABLE, COLUMN):
        op.add_column(
            TABLE,
            sa.Column(
                COLUMN,
                sa.String(length=20),
                nullable=False,
                server_default="implementation",
                comment=(
                    "Lifecycle phase this orchestrator execution belongs to: "
                    "'staging' or 'implementation'. Set at execution creation."
                ),
            ),
        )

    if not _has_constraint(conn, TABLE, CONSTRAINT):
        op.create_check_constraint(CONSTRAINT, TABLE, _check_clause())


def downgrade() -> None:
    conn = op.get_bind()

    if _has_constraint(conn, TABLE, CONSTRAINT):
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")

    if _has_column(conn, TABLE, COLUMN):
        op.drop_column(TABLE, COLUMN)
