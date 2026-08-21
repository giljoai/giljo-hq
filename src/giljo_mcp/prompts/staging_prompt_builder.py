# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Staging and thin-prompt builders.

Extracted from ThinClientPromptGenerator (Handover 0950g).
Builds staging-phase prompts and mission regeneration logic.
"""

import logging
from typing import Any

from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.config_manager import get_config
from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.models import Product, Project
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line


# BE-9275b: derived from the branding constant instead of a fresh literal.
_PREFIX = f"mcp__{MCP_ALIAS}__"

logger = logging.getLogger(__name__)


def _project_title(project: Any) -> str:
    has_taxonomy = bool(getattr(project, "project_type_id", None) or getattr(project, "series_number", None))
    if has_taxonomy:
        return f"{project.taxonomy_alias} {project.name}"
    return project.name


class StagingPromptBuilder:
    """Builds staging-phase prompts and handles mission regeneration."""

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
        """Generate thin prompt listing available MCP tools (Handover 0315).

        Returns ~600 token prompt (vs ~3500 in fat prompt) that references MCP tools
        for on-demand context fetching.

        Args:
            orchestrator_id: Job ID (WHAT - work order UUID)
            agent_id: Agent execution ID (WHO - executor UUID, for identity tracking only)
            project_id: Project UUID
            project: Project model
            product: Product model
            tool: AI coding agent (claude-code, codex, gemini, universal)
            field_toggles: User field toggle config (True=enabled, False=disabled)
            depth_config: User depth configuration
            user_id: Optional user ID

        Returns:
            Thin prompt with MCP tool references
        """
        config = get_config()
        # INF-5012b: prefer GILJO_PUBLIC_URL (set by demo/cloud deploys) over
        # reading the server's bind address from config, which produces ":7272"
        # URLs when the server is fronted by a reverse proxy.
        # BE-9442: via the one accessor, which strips the trailing slash — this
        # value is interpolated below as "{mcp_url}/health".
        mcp_url = get_public_url()

        api_key_configured = bool(config.server.api_key)
        auth_note = "(authenticated)" if api_key_configured else "(check config.yaml for API key)"

        # CE-0034 Task 2: Claude Code defers MCP tool schemas behind ToolSearch.
        # Without this single up-front call, health_check() and every other
        # mcp__<alias>__* call below raises InputValidationError. The hint
        # must live in THIS spawn prompt (not get_staging_instructions —
        # that's unreachable until ToolSearch loads its schema).
        # Mirrors ClaudePromptBuilder._build_context_recap (CE-0033 Task 5).
        toolsearch_bootstrap = ""
        if tool == "claude-code":
            toolsearch_bootstrap = (
                "STEP 0 — TOOLSEARCH BOOTSTRAP (Claude Code only — do this FIRST):\n"
                "Claude Code defers MCP tool schemas. You CANNOT call any\n"
                f"{_PREFIX}* tool (including health_check) until its schema\n"
                "is loaded. Fire this single call before the WORKFLOW below:\n"
                f"  {render_toolsearch_call_one_line()}\n"
                "After that, every tool in the canonical orchestrator set is callable.\n"
                "\n"
            )

        # BE-9260: TodoWrite is a Claude-Code-only tool -- this line used to render
        # unconditionally for every harness. Gate it the same way as the ToolSearch
        # bootstrap above; every other tool gets harness-neutral phrasing.
        todo_tracking_line = (
            "Claude Code: Use TodoWrite tool to track workflow progress."
            if tool == "claude-code"
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
        """Build the thin-client staging prompt text (Handover 0415).

        Args:
            project: Project model
            product: Product model
            orchestrator_id: Job ID (WHAT - work order UUID)
            project_id: Project UUID
            agent_id: Agent execution ID (WHO)
            mcp_url: Full MCP server URL
            tool: AI coding agent (claude-code, codex, gemini, universal).
                Claude Code defers MCP tool schemas behind ToolSearch and
                must bootstrap them before any other MCP call. CE-0035.

        Returns:
            Thin staging prompt (~113 tokens; ~+8 lines for claude-code).
        """
        # CE-0035: Claude Code defers MCP tool schemas — without a ToolSearch
        # bootstrap, the very first health_check() call raises
        # InputValidationError. Mirrors the block in build_thin_prompt
        # (CE-0034 Task 2) and ClaudePromptBuilder._build_context_recap
        # (CE-0033 Task 5). The hint MUST live in this spawn prompt because
        # get_staging_instructions is unreachable until ToolSearch loads
        # its schema. build_thin_prompt is a sibling method on a separate
        # call path; CE-0034 patched it but it does NOT render the
        # user-facing spawn prompt — this method does.
        toolsearch_bootstrap = ""
        if tool == "claude-code":
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
        """Regenerate orchestrator mission with current toggle config.

        Handover 0276: Enables "Stage Project refresh" — user changes settings,
        clicks "Stage Project", gets updated instructions immediately.

        Args:
            product: Product model with vision and config
            project: Project model with description
            field_toggles: Field toggle config (True=enabled, False=disabled)
            user_id: User ID for audit trail

        Returns:
            Regenerated mission string with current context
        """
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

        except Exception as _exc:  # Broad catch: prompt fallback, returns safe default
            logger.exception("[StagingPromptBuilder] Failed to regenerate mission")
            return project.mission or f"Mission for project: {project.name}"
