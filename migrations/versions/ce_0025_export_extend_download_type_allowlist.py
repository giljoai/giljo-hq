# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0025_export_extend_download_type_allowlist"
down_revision = "ce_0024_tasks_add_hidden"
branch_labels = None
depends_on = None


TABLE = "download_tokens"
CONSTRAINT = "ck_download_token_type"
OLD_ALLOWLIST = ("slash_commands", "agent_templates")
NEW_ALLOWLIST = ("slash_commands", "agent_templates", "tenant_export")


def _has_constraint(conn, table: str, constraint: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT 1 FROM information_schema.table_constraints "
            "WHERE table_name = :table AND constraint_name = :constraint"
        ),
        {"table": table, "constraint": constraint},
    )
    return result.first() is not None


def _check_clause(values: tuple[str, ...]) -> str:
    rendered = ", ".join(f"'{v}'" for v in values)
    return f"download_type IN ({rendered})"


def upgrade() -> None:
    conn = op.get_bind()

    if _has_constraint(conn, TABLE, CONSTRAINT):
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")

    op.create_check_constraint(CONSTRAINT, TABLE, _check_clause(NEW_ALLOWLIST))


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(f"DELETE FROM {TABLE} WHERE download_type = 'tenant_export'")  # noqa: S608
    )

    if _has_constraint(conn, TABLE, CONSTRAINT):
        op.drop_constraint(CONSTRAINT, TABLE, type_="check")

    op.create_check_constraint(CONSTRAINT, TABLE, _check_clause(OLD_ALLOWLIST))
