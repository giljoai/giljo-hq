# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0043_projects_execution_mode_nullable"
down_revision = "ce_0042_staged_agent_mailboxes"
branch_labels = None
depends_on = None


_TABLE = "projects"
_COLUMN = "execution_mode"
_OLD_DEFAULT = "multi_terminal"


def _column_is_nullable(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT is_nullable FROM information_schema.columns WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    row = result.first()
    return row is not None and row[0] == "YES"


def _column_has_server_default(conn, table: str, column: str) -> bool:
    result = conn.execute(
        sa.text(
            "SELECT column_default FROM information_schema.columns "
            "WHERE table_name = :table AND column_name = :column"
        ),
        {"table": table, "column": column},
    )
    row = result.first()
    return row is not None and row[0] is not None


def upgrade() -> None:
    conn = op.get_bind()

    if not _column_is_nullable(conn, _TABLE, _COLUMN) or _column_has_server_default(conn, _TABLE, _COLUMN):
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=sa.String(length=20),
            nullable=True,
            server_default=None,
        )


def downgrade() -> None:
    conn = op.get_bind()

    conn.execute(
        sa.text(f"UPDATE {_TABLE} SET {_COLUMN} = :val WHERE {_COLUMN} IS NULL"),
        {"val": _OLD_DEFAULT},
    )

    if _column_is_nullable(conn, _TABLE, _COLUMN) or not _column_has_server_default(conn, _TABLE, _COLUMN):
        op.alter_column(
            _TABLE,
            _COLUMN,
            existing_type=sa.String(length=20),
            nullable=False,
            server_default=sa.text(f"'{_OLD_DEFAULT}'"),
        )
