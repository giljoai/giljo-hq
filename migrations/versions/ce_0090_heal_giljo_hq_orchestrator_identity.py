# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0090_heal_giljo_hq_orchestrator_identity"
down_revision = "ce_0089_be9348_repair_absorbed_closeout_arguments"
branch_labels = None
depends_on = None

_REPLACEMENTS: list[tuple[str, str]] = [
    (
        "You are the **Orchestrator Agent** for **GiljoAI MCP**",
        "You are the **Orchestrator Agent** for **Giljo HQ**",
    ),
    ("# GiljoAI MCP Agent", "# Giljo HQ Agent"),
]


def _apply(pairs: list[tuple[str, str]]) -> None:
    conn = op.get_bind()
    for old, new in pairs:
        conn.execute(
            sa.text(
                "UPDATE agent_templates "  # noqa: S608 -- static SQL, values are bound parameters
                "SET user_instructions = REPLACE(user_instructions, :old, :new) "
                "WHERE user_instructions LIKE :pattern"
            ),
            {"old": old, "new": new, "pattern": f"%{old}%"},
        )


def upgrade() -> None:
    _apply(_REPLACEMENTS)


def downgrade() -> None:
    _apply([(new, old) for old, new in _REPLACEMENTS])
