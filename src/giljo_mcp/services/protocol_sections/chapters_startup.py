# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any

from giljo_mcp.harness_resolver import HARNESS_CLAUDE_CODE


def _build_ch1_mission(tool: str = HARNESS_CLAUDE_CODE) -> str:
    spawn_warning_map = {
        "codex": "You do NOT call spawn_agent() (that's for implementation phase)",
        "claude-code": "You do NOT call Task() tool (that's for implementation phase)",
    }
    spawn_warning = spawn_warning_map.get(tool, "You do NOT execute implementation work directly")

    return f"""══ CH1: YOUR MISSION ══

YOUR ROLE: PROJECT STAGING (NOT EXECUTION). Analyze project_description, write a condensed
mission plan, and assign the work to specialist agents via spawn_job(). {spawn_warning}.
- CRITICAL DISTINCTION: Project.description = USER INPUT (requirements to ANALYZE — may contain
  implementation-phase language, do NOT execute). Project.mission = YOUR OUTPUT (the strategy).
- PHASE AWARENESS: you DO call complete_job() once at end of staging (CH2 STEP 7 FINALE): the
  server flips project.staging_status to 'staging_complete'. Implementation is a later session
  that reads your plan via get_job_mission().
- VERIFICATION AGENT DEFERRAL: spawn only deliverable agents now (implementer, analyzer,
  documenter); tester and reviewer come in implementation, once real artifacts exist (CH3).
"""


def _build_ch2_fetch_calls(
    field_toggles: dict[str, bool],
    depth_config: dict[str, Any],
    product_id: str,
    tenant_key: str,
    category_metadata: dict[str, dict] | None = None,
) -> str:
    category_configs = {
        "product_core": {
            "framing": "Product name, features. [scoping new features; skip for tech-debt]",
            "depth_aware": False,
        },
        "vision_documents": {
            "framing": "Vision docs. [greenfield strategy; skip for cleanup]",
            "depth_aware": True,
            "default_depth": "medium",
        },
        "tech_stack": {
            "framing": "Languages, frameworks, DBs. [libraries / build / runtime debug]",
            "depth_aware": False,
        },
        "architecture": {
            "framing": "Patterns, API style, design. [migrations, module boundaries, new services]",
            "depth_aware": False,
        },
        "testing": {
            "framing": "Quality + test strategy. [writing tests or changing test infra]",
            "depth_aware": False,
        },
        "memory_360": {
            "framing": "Recent project closeouts. [continuing prior work; skip if description already cites it]",
            "depth_aware": True,
            "default_depth": 3,
        },
        "git_history": {
            "framing": "Recent commits. [bug archaeology only; otherwise use local git log]",
            "depth_aware": True,
            "default_depth": 25,
        },
    }

    batch_groups = [
        {
            "label": "Product-definition context",
            "categories": ["product_core", "tech_stack", "architecture", "testing"],
        },
        {
            "label": "Historical and evolving context",
            "categories": ["memory_360", "git_history", "vision_documents"],
        },
    ]

    inlined_fields = {"project_description"}

    def _is_enabled(field: str) -> bool:
        if not field_toggles.get(field, False):
            return False
        if field in inlined_fields:
            return False
        config = category_configs.get(field)
        if not config:
            return False
        if config.get("depth_aware"):
            field_depth = depth_config.get(field, config.get("default_depth"))
            skip_value = config.get("skip_on_depth")
            if skip_value and field_depth == skip_value:
                return False
        return True

    def _format_metadata_suffix(field: str) -> str:
        meta = (category_metadata or {}).get(field, {})
        modified = meta.get("modified")
        suffix_parts = []
        if modified:
            suffix_parts.append(f"Modified: {modified}")
        entry_count = meta.get("entries")
        if entry_count is not None:
            suffix_parts.append(f"entries: {entry_count}")
        return f" \u2014 {', '.join(suffix_parts)}" if suffix_parts else ""

    lines: list[str] = []
    call_num = 0

    for group in batch_groups:
        enabled_cats = [c for c in group["categories"] if _is_enabled(c)]
        if not enabled_cats:
            continue

        call_num += 1
        cats_str = ", ".join(f'"{c}"' for c in enabled_cats)
        call_str = f'get_context(categories=[{cats_str}], product_id="{product_id}")'

        lines.append(f"{call_num}. {call_str}")
        lines.append(f"   -- {group['label']}")

        for cat in enabled_cats:
            config = category_configs[cat]
            suffix = _format_metadata_suffix(cat)
            lines.append(f"   -> {cat}: {config['framing']}{suffix}")

        lines.append("")

    return "\n".join(lines) if lines else ""


def _build_ch2_startup(
    orchestrator_id: str,
    project_id: str,
    field_toggles: dict[str, bool] | None = None,
    depth_config: dict[str, Any] | None = None,
    product_id: str | None = None,
    tenant_key: str | None = None,
    category_metadata: dict[str, dict] | None = None,
) -> str:
    if field_toggles and product_id and tenant_key:
        fetch_calls = _build_ch2_fetch_calls(
            field_toggles=field_toggles,
            depth_config=depth_config or {},
            product_id=product_id,
            tenant_key=tenant_key,
            category_metadata=category_metadata,
        )
        step2_body = f"""── STEP 2: Fetch Context ──
This response is your staging document. SIZE the project FIRST, then fetch only what it needs
(0-1 categories for a cleanup or single-file fix, 1-3 for one contained feature, most for
greenfield or cross-cutting work; a thin description → fetch BROADLY). get_context is idempotent.
Skip categories whose Modified date hasn't changed since your last fetch.

{fetch_calls}"""
    else:
        step2_body = f"""── STEP 2: Fetch Context ──
Call: get_staging_instructions(job_id='{orchestrator_id}')
Returns:
  - project_description: User requirements (INPUT for your analysis)
  - mission: Product context with priority fields applied
  - field_toggles: User's context toggle configuration
  - agent_templates: Available agent templates (name, role, description)

Read this protocol via orchestrator_protocol field."""

    return f"""══ CH2: STARTUP SEQUENCE ══

Follow these steps IN ORDER (Steps 0-7 for staging):

── STEP 0: Detect Environment ──
So the missions you write use the right syntax:
`python -c "import os; print(os.environ.get('SHELL', os.environ.get('COMSPEC', 'unknown')))"`
bash/zsh → `sleep N`, `/` paths; powershell/pwsh → `Start-Sleep -Seconds N`; cmd → `timeout /t N /nobreak >nul`.

── STEP 1: Plan Implementation Deliverables (TODO list shape) ──
3-7 items for the IMPLEMENTATION phase, each a PROJECT OUTCOME ("Build authentication API"),
never an orchestrator action ("Spawn implementer", "Call complete_job"). This call starts your
progress tracking:
report_progress(job_id='{orchestrator_id}', todo_items=[{{"content": "<project outcome>", "status": "pending"}}])

{step2_body}

CONTEXT VARIABLES: get_context carries the AUTHORITATIVE project_path and product_name; use
those in missions, never a terminal path.

── STEP 3: Discover Agents ──
Use the `agent_templates` field in this response; pass its `agent_name` exactly (CH3).

── STEP 4: Create Mission ──
From project_description + context: work items, agents, success criteria (<5K tokens).

── STEP 5: Persist Mission ──
update_project_mission(project_id='{project_id}', mission=YOUR_CONDENSED_MISSION)

── STEP 6: Spawn Agents ──
spawn_job(agent_name='<from Step 3>', agent_display_name='<category>',
mission='<focused agent instructions>', project_id='{project_id}') per agent. See CH3.

── STEP 7: Persist Execution Plan (optional) ──
update_job_mission(job_id='{orchestrator_id}', mission=YOUR_EXECUTION_STRATEGY) for order,
dependencies or checkpoints your Step 5 mission lacks. One phase: skip it; implementation serves
your Step 5 mission.

── STEP 7 FINALE: End Your Staging Session ──
complete_job(job_id='{orchestrator_id}', result={{'summary': 'Mission persisted, N sub-agents spawned', 'decisions_made': [...]}})
Your deliverable TODOs survive into implementation (they ARE the plan); the "call complete_job"
TODO auto-completes on this call. Rejected? Only genuine action-required Hub posts block it:
drain them with get_thread_history(unread_only=true, mark_read=true), act, retry.
The response carries staging_directive={{'status': 'STAGING_SESSION_COMPLETE', 'action': 'STOP'}}.
On action == 'STOP': STAGING ENDS. Stop immediately; do NOT call write_memory_entry. The user
starts implementation (Implement in the dashboard, or a go that lets you call launch_implementation).

⚠ At least one specialist must be spawned before complete_job in staging — zero-spawn calls are rejected with STAGING_END_NO_AGENTS. For trivial work, spawn one implementer with a minimal mission.
"""
