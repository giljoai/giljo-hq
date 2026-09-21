# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import logging

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.http.url_resolver import get_public_url
from giljo_mcp.models.agent_identity import AgentExecution
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line


_TOOL_PREFIX = f"mcp__{MCP_ALIAS}__"
logger = logging.getLogger(__name__)




async def _resolve_conductor_job_id(run: dict, tenant_key: str, db: AsyncSession) -> str:
    cond_agent_id = run.get("conductor_agent_id")
    if not cond_agent_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This chain has no dedicated conductor yet (legacy run). Recreate the chain to mint one.",
        )
    row = await db.execute(
        select(AgentExecution.job_id).where(
            AgentExecution.agent_id == cond_agent_id,
            AgentExecution.tenant_key == tenant_key,
        )
    )
    job_id = row.scalar_one_or_none()
    if job_id is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conductor execution not found for this run.",
        )
    return str(job_id)


def _conductor_mcp_url() -> str:
    return get_public_url()


def _build_conductor_bootstrap(*, identity: dict, mcp_url: str, phase: str, harness_is_claude: bool) -> str:
    job_id = identity.get("job_id") or ""
    agent_id = identity.get("agent_id") or ""
    run_id = identity.get("run_id") or ""
    project_id = identity.get("project_id") or ""

    if project_id:
        role_line = (
            "You are the ORCHESTRATOR for ONE project in a linked chain. You stage, implement "
            "and close out THIS project only; the user starts the next project when this one closes."
        )
        project_line = f"  Project ID: {project_id}"
        returns_note = (
            "   -> Returns your full chain sub-orchestrator protocol (CH_SUB_ORCHESTRATOR):\n"
            "      your position in the chain, the Hub thread, and the close-out signal."
        )
    else:
        role_line = (
            "You are the dedicated CHAIN ORCHESTRATOR (project-less). You stage/drive ALL "
            "projects in this run; you own no project of your own."
        )
        project_line = "  Project ID: none (project-less)"
        returns_note = None

    fetch_tool = _TOOL_PREFIX if harness_is_claude else ""
    if phase == "staging":
        fetch_line = f"2. Fetch your chain protocol: {fetch_tool}get_staging_instructions(job_id='{job_id}')"
        protocol_note = returns_note or (
            "   -> Returns your full chain protocol (CH_CAPABILITY + CH_CHAIN_STAGING):\n"
            "      how each project is spawned and the authoritative staging script."
        )
    else:
        fetch_line = f"2. Fetch your chain protocol: {fetch_tool}get_job_mission(job_id='{job_id}')"
        protocol_note = returns_note or (
            "   -> Returns your full chain-drive protocol (CH_CHAIN_DRIVE): the\n"
            "      auto-continue loop that advances the chain project by project."
        )

    toolsearch_bootstrap = ""
    tool_prefix_line = (
        "  Tool names below are bare; your MCP client may expose them under a prefix "
        "(e.g. `mcp__<server>__<tool>`) — call them by the names your harness lists."
    )
    if harness_is_claude:
        toolsearch_bootstrap = (
            "STEP 0 — TOOLSEARCH BOOTSTRAP (Claude Code only — do this FIRST):\n"
            "Claude Code defers MCP tool schemas. You CANNOT call any\n"
            f"{_TOOL_PREFIX}* tool (including health_check) until its schema\n"
            "is loaded. Fire this single call before the START NOW workflow below:\n"
            f"  {render_toolsearch_call_one_line()}\n"
            "After that, every tool in the canonical orchestrator set is callable.\n"
            "\n"
        )
        tool_prefix_line = f"  Tool Prefix: {_TOOL_PREFIX}"

    health_check_call = f"{_TOOL_PREFIX}health_check()" if harness_is_claude else "health_check()"

    return f"""{role_line}

YOUR IDENTITY (use these in all MCP calls):
  YOUR Agent ID: {agent_id}
  YOUR Job ID: {job_id}
  Run ID: {run_id}
{project_line}

MCP CONNECTION:
  Server URL: {mcp_url}
{tool_prefix_line}

{toolsearch_bootstrap}START NOW:
1. Verify MCP: {health_check_call}
   -> Expected: {{"status": "healthy"}} - If failed, STOP and report error
{fetch_line}
{protocol_note}
"""
