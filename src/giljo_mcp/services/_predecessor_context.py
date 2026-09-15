# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ResourceNotFoundError, ValidationError

from giljo_mcp.platform_registry import SUBAGENT_EXECUTION_MODES
from giljo_mcp.repositories.agent_completion_repository import AgentCompletionRepository
from giljo_mcp.utils.log_sanitizer import sanitize


_REPLACEMENT_JOB_STATUSES: frozenset[str] = frozenset({"failed", "blocked", "decommissioned"})

_REPLACEMENT_RESULT_STATUSES: frozenset[str] = frozenset({"force_completed", "failed", "blocked", "error"})


def _detect_replacement_semantics(pred_job: Any, pred_execution: Any) -> bool:
    if pred_job is not None:
        job_status = str(getattr(pred_job, "status", "") or "").lower()
        if job_status in _REPLACEMENT_JOB_STATUSES:
            return True
    if pred_execution is not None:
        result_status = str((pred_execution.result or {}).get("status") or "").lower()
        if result_status in _REPLACEMENT_RESULT_STATUSES:
            return True
    return False


PREDECESSOR_CHAIN_PREAMBLE = """## PRIOR PHASE OUTPUT
You are continuing a workflow. The previous phase completed successfully and produced the work below. Use this as input for the work described in your mission below.

Previous Agent: {pred_display_name} (job_id: {predecessor_job_id})
Completion Summary: {pred_summary}
Commits: {pred_commits}

If you need full predecessor context (decisions, files changed, detail not in the summary above), call:
  get_agent_result(job_id="{predecessor_job_id}")

---
"""

PREDECESSOR_REPLACEMENT_PREAMBLE = """## PREDECESSOR CONTEXT (REPLACEMENT)
You are taking over from a previous agent who attempted this work but did not complete it cleanly. Read what they did, understand the gap, and complete or fix the work described in your mission below.

Previous Agent: {pred_display_name} (job_id: {predecessor_job_id})
Completion Summary: {pred_summary}
Commits: {pred_commits}

If git is enabled, run `git log --oneline -10` to see recent commits.
For full predecessor context, call:
  get_agent_result(job_id="{predecessor_job_id}")

---
"""

PREDECESSOR_BASE_BRANCH_BLOCK = """## BASE BRANCH (isolated-PR chain hand-off)
The previous phase delivered its work as an isolated branch/PR, not into a shared working tree. Base your work on its branch so you build ON its code, not a stale main:

  Branch to base on: {pred_branch}{pr_line}

Check out (or branch from) `{pred_branch}` before you start. The human reviews and merges that PR as the pacing gate between phases.

---
"""


def _build_base_branch_block(pred_result: dict[str, Any]) -> str:
    branch = (pred_result.get("branch") or "").strip()
    if not branch:
        return ""
    pr_url = (pred_result.get("pr_url") or "").strip()
    pr_line = f"\n  Predecessor PR:    {pr_url}" if pr_url else ""
    return PREDECESSOR_BASE_BRANCH_BLOCK.format(pred_branch=branch, pr_line=pr_line)


async def build_predecessor_context(
    session: AsyncSession,
    predecessor_job_id: str,
    tenant_key: str,
    project_id: str,
    mission: str,
    agent_display_name: str,
    execution_mode: str = "multi_terminal",
    *,
    logger: logging.Logger,
) -> str:
    repo = AgentCompletionRepository()
    pred_job = await repo.get_predecessor_job(session, tenant_key, predecessor_job_id)

    if not pred_job:
        raise ResourceNotFoundError(
            message=f"Predecessor job '{predecessor_job_id}' not found",
            context={"predecessor_job_id": predecessor_job_id, "tenant_key": tenant_key},
        )
    if pred_job.project_id != project_id:
        raise ValidationError(
            message="Predecessor job belongs to a different project",
            context={
                "predecessor_job_id": predecessor_job_id,
                "predecessor_project_id": pred_job.project_id,
                "target_project_id": project_id,
            },
        )

    if execution_mode in SUBAGENT_EXECUTION_MODES:
        logger.info(
            "[PREDECESSOR_CONTEXT] Skipped: subagent mode, orchestrator splices inline",
            extra={
                "predecessor_job_id": sanitize(predecessor_job_id),
                "execution_mode": sanitize(execution_mode),
                "successor_display_name": sanitize(agent_display_name),
            },
        )
        return mission

    pred_execution = await repo.get_completed_execution_for_job(session, tenant_key, predecessor_job_id)
    pred_display_name = pred_execution.agent_display_name if pred_execution else "Unknown"
    pred_result = (pred_execution.result or {}) if pred_execution else {}

    pred_summary = pred_result.get("summary", "No summary available")
    if len(pred_summary) > 2000:
        pred_summary = pred_summary[:2000] + " [TRUNCATED]"

    pred_commits = pred_result.get("commits", ["No commits recorded"])
    if len(pred_commits) > 10:
        pred_commits = [*pred_commits[:10], f"... and {len(pred_commits) - 10} more"]

    is_replacement = _detect_replacement_semantics(pred_job, pred_execution)
    template = PREDECESSOR_REPLACEMENT_PREAMBLE if is_replacement else PREDECESSOR_CHAIN_PREAMBLE
    predecessor_context = template.format(
        pred_display_name=pred_display_name,
        predecessor_job_id=predecessor_job_id,
        pred_summary=pred_summary,
        pred_commits=pred_commits,
    )

    base_branch_block = _build_base_branch_block(pred_result)

    mission = predecessor_context + base_branch_block + mission
    logger.info(
        "[PREDECESSOR_CONTEXT] Injected predecessor preamble",
        extra={
            "predecessor_job_id": sanitize(predecessor_job_id),
            "execution_mode": sanitize(execution_mode),
            "preamble_kind": "replacement" if is_replacement else "chain",
            "isolated_pr_handoff": bool(base_branch_block),
            "successor_display_name": sanitize(agent_display_name),
            "predecessor_display_name": sanitize(pred_display_name),
        },
    )
    return mission
