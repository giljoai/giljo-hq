# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0049_heal_tool_rename_user_instructions"
down_revision = "ce_0048_roadmap_item_blocked"
branch_labels = None
depends_on = None

_DEFAULT_TEMPLATE_NAMES = (
    "orchestrator",
    "implementer",
    "tester",
    "analyzer",
    "reviewer",
    "documenter",
)

_RENAMES: list[tuple[str, str]] = [
    ("get_agent_mission", "get_job_mission"),
    ("update_agent_mission", "update_job_mission"),
    ("fetch_context", "get_context"),
    ("write_360_memory", "write_memory_entry"),
    ("close_project_and_update_memory", "write_project_closeout"),
    ("inspect_messages", "get_messages"),
    ("update_product_fields", "update_product_context"),
    ("submit_tuning_review", "propose_product_context_update"),
]

_NAMES_TUPLE = ", ".join(f"'{n}'" for n in _DEFAULT_TEMPLATE_NAMES)


def upgrade() -> None:
    conn = op.get_bind()
    for old_name, new_name in _RENAMES:
        conn.execute(
            sa.text(
                f"UPDATE agent_templates "  # noqa: S608
                f"SET user_instructions = REPLACE(user_instructions, :old, :new) "
                f"WHERE name IN ({_NAMES_TUPLE}) "
                f"AND user_instructions LIKE :pattern"
            ),
            {"old": old_name, "new": new_name, "pattern": f"%{old_name}%"},
        )


def downgrade() -> None:
    conn = op.get_bind()
    for old_name, new_name in _RENAMES:
        conn.execute(
            sa.text(
                f"UPDATE agent_templates "  # noqa: S608
                f"SET user_instructions = REPLACE(user_instructions, :new, :old) "
                f"WHERE name IN ({_NAMES_TUPLE}) "
                f"AND user_instructions LIKE :pattern"
            ),
            {"old": old_name, "new": new_name, "pattern": f"%{new_name}%"},
        )
