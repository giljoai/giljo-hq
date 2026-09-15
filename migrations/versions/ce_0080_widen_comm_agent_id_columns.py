# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op
from sqlalchemy import inspect


revision = "ce_0080_widen_comm_agent_id_columns"
down_revision = "ce_0079_users_tutorial_reentry_state"
branch_labels = None
depends_on = None


_WIDEN: tuple[tuple[str, str, bool], ...] = (
    ("messages", "from_agent_id", True),
    ("message_recipients", "agent_id", False),
    ("message_acknowledgments", "agent_id", False),
    ("message_completions", "agent_id", False),
    ("sequence_runs", "conductor_agent_id", True),
)


def _current_length(inspector, table: str, column: str) -> int | None:
    for col in inspector.get_columns(table):
        if col["name"] == column:
            return getattr(col["type"], "length", None)
    return None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, column, nullable in _WIDEN:
        if table not in existing_tables:
            continue
        if _current_length(inspector, table, column) == 64:
            continue
        op.alter_column(
            table,
            column,
            type_=sa.String(length=64),
            existing_type=sa.String(length=36),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing_tables = set(inspector.get_table_names())

    for table, column, _nullable in _WIDEN:
        if table not in existing_tables:
            continue
        if _current_length(inspector, table, column) == 36:
            continue
        op.execute(f"ALTER TABLE {table} ALTER COLUMN {column} TYPE VARCHAR(36) USING substring({column} for 36)")
