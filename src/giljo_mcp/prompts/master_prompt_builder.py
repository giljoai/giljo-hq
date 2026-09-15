# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.branding import MCP_ALIAS
from giljo_mcp.exceptions import ValidationError
from giljo_mcp.platform_registry import VALID_EXECUTION_MODES
from giljo_mcp.prompts._canonical_tool_list import render_toolsearch_call_one_line


_TOOL_PREFIX = f"mcp__{MCP_ALIAS}__"


def _render_project_line(index: int, project: dict[str, Any]) -> str:
    alias = str(project.get("taxonomy_alias") or "").strip()
    name = str(project.get("name") or "(untitled)").strip()
    mission = str(project.get("mission") or "").strip()
    heading = f"{index}. {alias} {name}".strip()
    body = mission if mission else "(no mission authored yet -- write one with update_project_mission)"
    return f"{heading}\n   project_id: {project.get('project_id')}\n   mission: {body}"


def build_master_prompt(
    *,
    projects: list[dict[str, Any]],
    execution_mode: str,
    mcp_url: str,
    harness_is_claude: bool,
) -> str:
    if not projects:
        raise ValidationError(
            "A master prompt needs at least one staged project. A seed that lists none "
            "reads as valid and then does nothing.",
            context={"projects": 0},
        )
    if execution_mode not in VALID_EXECUTION_MODES:
        raise ValidationError(
            f"Invalid execution_mode '{execution_mode}'. Valid modes: {sorted(VALID_EXECUTION_MODES)}.",
            context={"valid_modes": sorted(VALID_EXECUTION_MODES)},
        )

    project_block = "\n\n".join(_render_project_line(i, p) for i, p in enumerate(projects, start=1))
    project_ids = ", ".join(f'"{p.get("project_id")}"' for p in projects)

    if harness_is_claude:
        bootstrap = (
            "STEP 0 -- TOOLSEARCH BOOTSTRAP (Claude Code only -- do this FIRST):\n"
            "Claude Code defers MCP tool schemas. You CANNOT call any\n"
            f"{_TOOL_PREFIX}* tool (including health_check) until its schema is loaded.\n"
            "Fire this single call before the workflow below:\n"
            f"  {render_toolsearch_call_one_line()}\n\n"
        )
        tool_note = f"  Tool Prefix: {_TOOL_PREFIX}"
    else:
        bootstrap = ""
        tool_note = (
            "  Tool names below are bare; your MCP client may expose them under a prefix\n"
            "  (e.g. `mcp__<server>__<tool>`) -- call them by the names your harness lists."
        )

    return f"""You are the CONDUCTOR for this run. You drive the projects below, one after another.
You own no project of your own, and no server-side agent was minted for you -- this
session IS the conductor.

MCP CONNECTION:
  Server URL: {mcp_url}
{tool_note}

EXECUTION MODE: {execution_mode}
  Every project in this run is driven this way. It was chosen by the user at launch;
  do not ask again and do not change it partway.

THE RUN ({len(projects)} project{"s" if len(projects) != 1 else ""}, in this order):

{project_block}

{bootstrap}START NOW:
1. Verify MCP: health_check()
   -> Expected: {{"status": "healthy"}}. If it fails, STOP and report the error.
2. Record the run so the dashboard can show it and a crash can resume it:
   link_projects(project_ids=[{project_ids}])
   -> The chain is a RECORD, not a workflow. You are what drives it; the record is
      what survives you. Do this BEFORE starting work, not after.
3. Drive the projects in the order listed. For each one, in turn:
   a. get_implementation_prompt(project_id) for the project's own orchestrator prompt.
      If it refuses, the refusal names the exact next step -- follow it rather than
      working around it.
   b. Carry that project to completion, then close it out, before starting the next.

THE HUMAN GATE IS NOT YOURS TO CROSS ON YOUR OWN.
Every project here is STAGED. Staged is not launched: implementation is released by a
separate, deliberate authorisation -- the dashboard's Implement button, or
launch_implementation over MCP where this account allows it. If a project has not been
released, STOP on that project and say so. Do not skip it, and do not start the next
one in its place.
"""
