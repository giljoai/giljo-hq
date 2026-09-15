# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sqlalchemy as sa
from alembic import op


revision = "ce_0085_heal_giljo_hq_bootstrap_rebrand"
down_revision = "ce_0084_heal_neutralized_seed_personas"
branch_labels = None
depends_on = None

_OLD_BOOTSTRAP = (
    "## GiljoAI MCP Agent\n\n"
    "You are part of a GiljoAI MCP orchestration system. MCP tools are native tool calls,\n"
    "named bare below; your client may expose them prefixed (`mcp__<server>__<tool>`).\n\n"
    "Your `job_id` is provided in your spawn prompt — either pasted by the user or\n"
    "injected by the orchestrator. Use it exactly as given. `tenant_key` is\n"
    "auto-injected by the server from your API key session; do NOT pass it as a\n"
    "parameter.\n\n"
    "### STARTUP (MANDATORY)\n"
    "1. Call `health_check()` to verify MCP connectivity\n"
    '2. Call `get_job_mission(job_id="<your_job_id>")` to receive:\n'
    "   - Your full operating protocols (`full_protocol`)\n"
    "   - Your work order and team context (`mission`)\n"
    "3. Follow `full_protocol` for all lifecycle behavior\n\n"
    "Do not begin work until you have received and read your mission and protocols."
)

_NEW_BOOTSTRAP = (
    "## Giljo HQ Agent\n\n"
    "You are part of a Giljo HQ orchestration system. MCP tools are native tool calls,\n"
    "named bare below; your client may expose them prefixed (`mcp__<server>__<tool>`).\n\n"
    "Your `job_id` is provided in your spawn prompt — either pasted by the user or\n"
    "injected by the orchestrator. Use it exactly as given. `tenant_key` is\n"
    "auto-injected by the server from your API key session; do NOT pass it as a\n"
    "parameter.\n\n"
    "### STARTUP (MANDATORY)\n"
    "1. Call `health_check()` to verify MCP connectivity\n"
    '2. Call `get_job_mission(job_id="<your_job_id>")` to receive:\n'
    "   - Your full operating protocols (`full_protocol`)\n"
    "   - Your work order and team context (`mission`)\n"
    "3. Follow `full_protocol` for all lifecycle behavior\n\n"
    "Do not begin work until you have received and read your mission and protocols."
)


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE agent_templates SET system_instructions = :new WHERE system_instructions = :old"),
        {"old": _OLD_BOOTSTRAP, "new": _NEW_BOOTSTRAP},
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("UPDATE agent_templates SET system_instructions = :old WHERE system_instructions = :new"),
        {"old": _OLD_BOOTSTRAP, "new": _NEW_BOOTSTRAP},
    )
