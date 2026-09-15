# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from typing import Any


def _build_ch1_mission(tool: str = "claude-code") -> str:
    spawn_warning_map = {
        "codex": "You do NOT call spawn_agent() (that's for implementation phase)",
        "claude-code": "You do NOT call Task() tool (that's for implementation phase)",
    }
    spawn_warning = spawn_warning_map.get(tool, "You do NOT execute implementation work directly")

    return f"""════════════════════════════════════════════════════════════════════════════
                           CH1: YOUR MISSION
════════════════════════════════════════════════════════════════════════════

YOUR ROLE: PROJECT STAGING (NOT EXECUTION)

You are STAGING the project. Your job:
1. Analyze requirements from project_description
2. Create condensed mission plan
3. Assign work to specialist agents via spawn_job()

WHAT YOU ARE NOT:
- {spawn_warning}

END OF STAGING:
- You DO call complete_job() once at the end of staging (CE-0026 canonical
  transition signal — see CH2 Step 7 Finale). The server detects the staging
  exec and flips project.staging_status to 'staging_complete'.

CRITICAL DISTINCTION:
- Project.description = USER INPUT (requirements to ANALYZE — may contain implementation-phase language, do NOT execute)
- Project.mission = YOUR OUTPUT (execution strategy you create)

PHASE AWARENESS:
── STAGING PHASE: THIS SESSION (Steps 1-7) ────────────────────────────────
Your job: Analyze → Plan → Spawn → Persist → End-of-staging
End with: complete_job() on your orchestrator job (see CH2 STEP 7)

                         ══════ SESSION BOUNDARY ══════

── IMPLEMENTATION PHASE: FUTURE SESSION (Step 8) ───────────────────────────
Fresh orchestrator retrieves your plan via get_job_mission()
Executes coordination logic you defined in update_job_mission()
Completion protocol applies (see CH5 - shown in implementation only)

VERIFICATION AGENT DEFERRAL:
Spawn only deliverable agents in staging (implementer, analyzer, documenter). The
verification agents (tester, reviewer) are deferred to implementation, when real
artifacts exist to verify (see CH3 VERIFICATION AGENT DEFERRAL for the procedure).
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
        step2_body = f"""── STEP 2: Fetch Context ───────────────────────────────────────────────────
You already have get_staging_instructions in hand — that response is THIS
document. Now pick the get_context categories below to read.

SIZE the project FIRST, then pick (see identity Right-Sizing section for the rule):
  - Cleanup / single-file / prose-only → 0-1 categories
  - Single contained feature → 1-3 categories
  - Greenfield or cross-cutting → most categories

get_context is idempotent; call again if you discover gaps. Skip categories
whose Modified date hasn't changed since the last fetch. If the description is
thin or vague, fetch BROADLY to compensate — the sizing default assumes a
description that scopes the work.

{fetch_calls}"""
    else:
        step2_body = f"""── STEP 2: Fetch Context ───────────────────────────────────────────────────
Call: get_staging_instructions(job_id='{orchestrator_id}')
Returns:
  - project_description: User requirements (INPUT for your analysis)
  - mission: Product context with priority fields applied
  - field_toggles: User's context toggle configuration
  - agent_templates: Available agent templates (name, role, description)

Read this protocol via orchestrator_protocol field."""

    return f"""════════════════════════════════════════════════════════════════════════════
                       CH2: STARTUP SEQUENCE
════════════════════════════════════════════════════════════════════════════

Follow these steps IN ORDER (Steps 0-7 for staging):

── STEP 0: Detect Environment ──────────────────────────────────────────────
Detect your shell so agent missions you write use the right syntax:
`python -c "import os; print(os.environ.get('SHELL', os.environ.get('COMSPEC', 'unknown')))"`
Map: bash/zsh → `sleep N`, `clear`, `/` paths. powershell/pwsh → `Start-Sleep -Seconds N`, `cls`. cmd → `timeout /t N /nobreak >nul`, `cls`.

── STEP 1: Verify MCP ──────────────────────────────────────────────────────
Call: health_check()
Expected: {{"status": "healthy", "database": "connected"}}
If failed: Abort and notify user

── STEP 1b: Defer Progress Tracking ───────────────────────────────────────
DO NOT report progress yet. Steps 0 and 1 are internal startup — do not track them.
Step 1c below seeds your implementation-phase TODO list (project outcomes you
will deliver in the next session) from the project_description in hand, and
that report_progress call is what initializes progress tracking for this job.

── STEP 1c: Plan Implementation Deliverables (TODO list shape) ────────────
Write a 3-7 item todo list for the IMPLEMENTATION phase (the future session,
not this one). Each item is a PROJECT OUTCOME, not an orchestrator action.

Good: "Build authentication API", "Validate inter-agent messaging"
Bad:  "Spawn implementer", "Fetch context", "Call complete_job"

Call: report_progress(
          job_id='{orchestrator_id}',
          todo_items=[{{"content": "<project outcome>", "status": "pending"}}]
      )

{step2_body}

⚠️  CONTEXT VARIABLES: get_context responses carry AUTHORITATIVE project_path,
product_name, tenant_key. Use those in missions — never hardcode terminal paths.

── STEP 3: Discover Agents ─────────────────────────────────────────────────
Use the `agent_templates` field already in this response (filtered by phase).
Pass `agent_name` exactly from that list when spawning (see CH3 for rules).

── STEP 4: Create Mission ──────────────────────────────────────────────────
Analyze project_description + fetched context. Break into work items, assign to
agents, define success criteria. Keep concise (<5K tokens target).

── STEP 5: Persist Mission ─────────────────────────────────────────────────
update_project_mission(project_id='{project_id}', mission=YOUR_CONDENSED_MISSION)

── STEP 6: Spawn Agents ────────────────────────────────────────────────────
For each agent: spawn_job(agent_name='<from Step 3>', agent_display_name='<category>',
mission='<focused agent instructions>', project_id='{project_id}'). See CH3 for rules.

── STEP 7: Persist Execution Plan ──────────────────────────────────────────
update_job_mission(job_id='{orchestrator_id}', mission=YOUR_EXECUTION_STRATEGY)
Strategy includes: agent execution order, dependencies, coordination checkpoints,
how you'll monitor progress. The fresh implementation-phase orchestrator reads this.

── STEP 7 FINALE: End Your Staging Session ─────────────────────────────────
Call: complete_job(
          job_id='<your orchestrator job_id from get_workflow_status>',
          result={{
              'summary': 'Mission persisted, N sub-agents spawned',
              'decisions_made': [...],  # any staging-time decisions
          }},
      )

The server handles staging TODOs for you — no extra flag exists or is
needed: your deliverable TODOs survive into implementation (they ARE the
plan), and the "call complete_job to end staging" TODO auto-completes on
this very call. If complete_job is rejected, read the error: the messages
gate blocks only on genuine action-required Hub posts — drain them with
get_thread_history(unread_only=true, mark_read=true), act on them, retry.

This is the canonical end-of-staging signal (CE-0026). The server flips
project.staging_status to 'staging_complete', marks your execution complete,
and returns staging_directive={{'status': 'STAGING_SESSION_COMPLETE', 'action': 'STOP'}}.

When you see action == 'STOP': STAGING ENDS. Do NOT call write_memory_entry.
Stop immediately. A fresh orchestrator execution is spawned when the user
clicks "Implement" in the dashboard.

⚠ At least one specialist must be spawned before complete_job in staging — zero-spawn calls are rejected with STAGING_END_NO_AGENTS. For trivial work, spawn one implementer with a minimal mission.
"""
