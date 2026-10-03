# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging
from typing import Any

from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.config_manager import get_config
from giljo_mcp.harness_resolver import HARNESS_CLAUDE_CODE
from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.models import Product, Project
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line


_PREFIX = f"mcp__{MCP_ALIAS}__"

logger = logging.getLogger(__name__)


def _project_title(project: Any) -> str:
    has_taxonomy = bool(getattr(project, "project_type_id", None) or getattr(project, "series_number", None))
    if has_taxonomy:
        return f"{project.taxonomy_alias} {project.name}"
    return project.name


class StagingPromptBuilder:

    def build_thin_prompt(
        self,
        orchestrator_id: str,
        agent_id: str,
        project_id: str,
        project: Any,
        product: Any,
        tool: str,
        field_toggles: dict[str, bool],
        depth_config: dict[str, Any],
        user_id: str | None = None,
    ) -> str:
        config = get_config()
        mcp_url = get_public_url()

        api_key_configured = bool(config.server.api_key)
        auth_note = "(authenticated)" if api_key_configured else "(check config.yaml for API key)"

        toolsearch_bootstrap = ""
        if tool == HARNESS_CLAUDE_CODE:
            toolsearch_bootstrap = (
                "STEP 0 — TOOLSEARCH BOOTSTRAP (Claude Code only — do this FIRST):\n"
                "Claude Code defers MCP tool schemas. You CANNOT call any\n"
                f"{_PREFIX}* tool (including health_check) until its schema\n"
                "is loaded. Fire this single call before the WORKFLOW below:\n"
                f"  {render_toolsearch_call_one_line()}\n"
                "After that, every tool in the canonical orchestrator set is callable.\n"
                "\n"
            )

        todo_tracking_line = (
            "Claude Code: Use TodoWrite tool to track workflow progress."
            if tool == HARNESS_CLAUDE_CODE
            else "Use your task list to track workflow progress."
        )

        return f"""I am Orchestrator for GiljoAI Project "{_project_title(project)}".

IDENTITY:
- Orchestrator Agent ID: {agent_id}
- Job ID: {orchestrator_id}
- Project ID: {project_id}

MCP CONNECTION:
- Server URL: {mcp_url}
- Auth Status: {auth_note}
- Tool names below are bare; your MCP client may expose them under a prefix (e.g. `mcp__<server>__<tool>`) — call them by the names your harness lists.

YOUR ROLE: PROJECT STAGING (NOT EXECUTION)
You are STAGING the project by creating a mission plan. You will NOT execute the work yourself.
Your job is to: 1) Analyze requirements, 2) Create mission plan, 3) Assign work to specialist agents.

PROJECT CONTEXT (Inline - ~200 tokens):
- Name: {project.name}
- Description: {project.description or "(No description provided)"}
- Mission: {project.mission or "(Mission will be created by you)"}

{toolsearch_bootstrap}WORKFLOW:
1. Verify MCP connection: health_check()
   → Expected: {{"status": "healthy", "database": "connected"}}
   → If failed: STOP and report error - do NOT proceed
2. Fetch complete context: get_staging_instructions('{orchestrator_id}')
   → Returns configured context (vision, tech stack, architecture, memory, git history, templates)
   → User toggle/depth configuration automatically applied server-side
   → Depth configuration (chunking, commit count, etc.) pre-configured
3. Create condensed mission plan from fetched context
4. Persist mission: update_project_mission('{project_id}', mission)
5. Spawn specialist agents: spawn_job(agent_display_name, agent_name, mission, '{project_id}')
   → SAVE each response's agent_id UUID - needed for UUID-based messaging
6. Monitor: get_workflow_status('{project_id}')
7. End your staging session: complete_job(job_id='{orchestrator_id}', result={{'summary': 'Mission created, N agents spawned: [list names]'}})
   → Server flips project.staging_status to 'staging_complete' (enables the Implement button in UI)
   → Response includes staging_directive.action='STOP' — your session ends NOW

{todo_tracking_line}

MESSAGING RULE: Always use agent_id UUIDs when addressing agents via post_to_thread(to_participant=...).
Each spawn_job() returns an agent_id UUID. Never use display names in to_participant.

CRITICAL DISTINCTIONS:
- Project.description = User-written requirements (already provided above)
- Project.mission = YOUR OUTPUT (condensed execution plan you CREATE in Step 2)
- Agent jobs = Specialist agents who will DO THE ACTUAL WORK (you coordinate them)

MCP CORE TOOLS (Always Available):
✓ health_check() - Verify MCP connection
✓ get_staging_instructions('{orchestrator_id}') - Fetch complete prioritized context
✓ update_project_mission('{project_id}', mission) - Save mission plan
✓ spawn_job(agent_display_name, agent_name, mission, '{project_id}') - Create agents (returns agent_id UUID)
✓ get_workflow_status('{project_id}') - Check spawned agents
✓ post_to_thread(thread_id, content, from_agent, to_participant, requires_action) - Message a teammate on your coordination thread (agent_id UUIDs in to_participant)

CONNECTION TROUBLESHOOTING:
If MCP fails: Check server running at {mcp_url}/health
Logs: ~/.giljo_mcp/logs/mcp_adapter.log

Begin by verifying MCP connection, then fetch complete context, and CREATE the mission plan.
"""

    def build_staging_prompt(
        self,
        project: Any,
        product: Any,
        orchestrator_id: str,
        project_id: str,
        agent_id: str,
        mcp_url: str,
        tool: str = "universal",
    ) -> str:
        toolsearch_bootstrap = ""
        if tool == HARNESS_CLAUDE_CODE:
            toolsearch_bootstrap = (
                "STEP 0 — TOOLSEARCH BOOTSTRAP (Claude Code only — do this FIRST):\n"
                "Claude Code defers MCP tool schemas. You CANNOT call any\n"
                f"{_PREFIX}* tool (including health_check) until its schema\n"
                "is loaded. Fire this single call before the START NOW workflow below:\n"
                f"  {render_toolsearch_call_one_line()}\n"
                "After that, every tool in the canonical orchestrator set is callable.\n"
                "\n"
            )

        return f"""You are the ORCHESTRATOR for project "{_project_title(project)}"

YOUR IDENTITY (use these in all MCP calls):
  YOUR Agent ID: {agent_id}
  YOUR Job ID: {orchestrator_id}
  THE Project ID: {project_id}

MCP Server: {mcp_url}

{toolsearch_bootstrap}Tool names below are bare; your MCP client may expose them under a prefix
(e.g. `mcp__<server>__<tool>`) — call them by the names your harness lists.

START NOW:
1. Verify MCP: health_check()
   → Expected: {{"status": "healthy"}} - If failed, STOP and report error
2. Fetch instructions: get_staging_instructions(job_id='{orchestrator_id}')
   → Response includes orchestrator_protocol (5-chapter workflow) AND orchestrator_identity (behavioral guidance)
"""

    def regenerate_mission(
        self, product: Product, project: Project, field_toggles: dict[str, bool], user_id: str | None
    ) -> str:
        try:
            mission_parts = []

            if product and product.description:
                mission_parts.append(f"## Product\n{product.description}")

            if project.description:
                mission_parts.append(f"## Project Goal\n{project.description}")

            if project.mission:
                mission_parts.append(f"## Mission\n{project.mission}")

            if field_toggles.get("tech_stack", True) and product and product.tech_stack:
                ts = product.tech_stack
                tech_parts = []
                if ts.programming_languages:
                    tech_parts.append(f"Languages: {ts.programming_languages}")
                if ts.frontend_frameworks:
                    tech_parts.append(f"Frontend: {ts.frontend_frameworks}")
                if ts.backend_frameworks:
                    tech_parts.append(f"Backend: {ts.backend_frameworks}")
                if tech_parts:
                    mission_parts.append(f"## Tech Stack\n{chr(10).join(tech_parts)}")

            if field_toggles.get("architecture", True) and product and product.architecture:
                arch = product.architecture
                if arch.primary_pattern:
                    mission_parts.append(f"## Architecture\n{arch.primary_pattern}")

            if mission_parts:
                regenerated = "\n\n".join(mission_parts)
                logger.debug(
                    f"[StagingPromptBuilder] Mission regenerated: {len(mission_parts)} sections, "
                    f"{len(regenerated)} chars"
                )
                return regenerated
            logger.warning("[StagingPromptBuilder] No mission parts available for regeneration")
            return project.mission or f"Mission for project: {project.name}"

        except Exception as _exc:
            logger.exception("[StagingPromptBuilder] Failed to regenerate mission")
            return project.mission or f"Mission for project: {project.name}"
