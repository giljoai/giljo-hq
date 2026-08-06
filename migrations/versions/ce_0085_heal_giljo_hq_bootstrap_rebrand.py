# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9275b: heal the "GiljoAI MCP" -> "Giljo HQ" bootstrap rebrand for existing tenants.

Revision ID: ce_0085_heal_giljo_hq_bootstrap_rebrand
Revises: ce_0084_heal_neutralized_seed_personas
Create Date: 2026-07-24

BE-9275b flipped the MCP tool prefix in agent-facing prose from `mcp__giljo_mcp__`
to `mcp__giljo_hq__` (derived from ``branding.MCP_ALIAS``) and reworded the shared
MCP bootstrap section (``template_seeder._get_mcp_bootstrap_section()``) from
"GiljoAI MCP" to "Giljo HQ" (derived from ``branding.PRODUCT_NAME``). That bootstrap
is stored verbatim in every non-orchestrator role's ``agent_templates.system_instructions``
column at seed time.

``refresh_tenant_template_instructions`` is operator-triggered only and does NOT
run on startup (same gap ``ce_0049`` and ``ce_0084`` healed for their own bootstrap
edits) -- this migration does its own raw-SQL heal so existing tenants actually
receive the reworded bootstrap via the path that runs on every boot.

Scope: ``system_instructions`` only, for rows whose column still byte-matches the
EXACT pre-BE-9275b bootstrap string produced by ``_get_mcp_bootstrap_section()``.
The orchestrator role is in ``SYSTEM_MANAGED_ROLES`` (``template_seeder.py``) and
never gets its own ``agent_templates`` row seeded -- callers read its identity
prompt straight from code, so there is nothing in the DB to heal for it. The
in-repo template_renderer.py tolerates BOTH the old and new bootstrap shapes
(marker/heading dual-check) regardless of whether this migration has run yet, so
a CE self-hoster who never re-runs migrations still renders correctly -- this
migration is a data cleanliness pass, not a correctness dependency.

Idempotent: the UPDATE's WHERE clause requires the column to still hold the OLD
text, so a second run (the CE installer reruns `alembic upgrade head` on every
boot) matches zero rows and is a clean no-op.

Edition Scope: CE -- ``agent_templates`` is a CE table (``migrations/versions/``).
SaaS inherits this migration unchanged via its next ``preDeploy`` alembic run.
"""

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
