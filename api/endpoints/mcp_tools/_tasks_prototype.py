# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6039 (project BE-6255): MCP Tasks extension -- SHAPE prototype + mapping core.

NO-SHIP-UNTIL-GA. Additive and DORMANT by default. Demonstrates the ~1:1 mapping between
our hand-rolled job/agent lifecycle and the upstream MCP Tasks extension
(``io.modelcontextprotocol/tasks``), so the GA wiring is a known quantity.

What lands now (reusable, GA-surviving):
- ``map_execution_status_to_task_status`` -- the 1:1 status table (our AgentExecution
  status -> MCP ``TaskStatus``). This is the load-bearing mapping; it survives to GA.
- ``derive_aggregate_task_status`` -- reduces a project-level ``get_workflow_status``
  count payload to a single ``TaskStatus`` + message (a documented approximation for the
  project surface; the precise mapping at GA is per-JOB: one spawn_job == one Task).
- ``build_task_view`` -- constructs a real ``mcp.types.Task`` / ``CreateTaskResult`` (so
  the shape is validated against the installed SDK) and returns it as a plain dict.
- ``maybe_attach_task_view`` -- when ``GILJO_TASKS_PROTOTYPE`` is set AND the client
  declares the tasks extension capability, attaches a ``task_view`` to ``get_workflow_status``
  output. Otherwise returns the result unchanged.

What does NOT land now (it's the GA-SDK production step, per BE-6255 constraint C2): a
custom persistent ``TaskStore`` mapping onto ``agent_jobs``, protocol-level ``tasks/get`` /
``tasks/update`` handling, and ``notifications/tasks``. The installed mcp 1.27.2 task support
is the pre-SEP-2663 experimental shape (blocking ``tasks/result`` + ``tasks/list``, no
``tasks/update``, its own in-memory store, unscoped under stateless sessions, not exposed by
FastMCP), so wiring it in production now would be churn against a shape GA changes. This
prototype proves the mapping without that integration.

Edition Scope: Both.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from typing import Any

from mcp.server.fastmcp import Context


logger = logging.getLogger(__name__)

_FLAG_ENV = "GILJO_TASKS_PROTOTYPE"
_TRUTHY = {"1", "true", "yes", "on"}

# Default freshness/poll hints for the prototype task view (milliseconds).
_DEFAULT_TTL_MS = 3_600_000  # 1h
_DEFAULT_POLL_INTERVAL_MS = 2_000  # 2s

# 1:1 mapping: our AgentExecution status -> MCP TaskStatus
# (working|input_required|completed|failed|cancelled). The reusable, GA-surviving core.
# Unknown/unmapped statuses default to "working" (non-terminal, safe).
# BE-9058: executions actually write "complete" (see AgentExecution.status comment);
# the mapping previously carried only the speculative "completed" token, so a finished
# execution fell through to the default and reported as still working. Both spellings
# map now (tolerance for any row that ever carried the long form).
_EXECUTION_TO_TASK_STATUS: dict[str, str] = {
    "working": "working",
    "pending": "working",
    "silent": "working",
    "blocked": "working",  # waiting on a dependency -- non-terminal; surfaced via statusMessage
    "awaiting_user": "input_required",
    "complete": "completed",
    "completed": "completed",
    "failed": "failed",
    "closed": "cancelled",
    "decommissioned": "cancelled",
    "terminated": "cancelled",
    "cancelled": "cancelled",
}


def _tasks_prototype_enabled() -> bool:
    """Feature flag, default OFF (NO-SHIP-UNTIL-GA)."""
    return os.getenv(_FLAG_ENV, "").strip().lower() in _TRUTHY


def _client_supports_tasks(ctx: Context) -> bool:
    """Best-effort: True only if the client declared the tasks extension capability.

    The exact capability shape firms up at GA (RC: ``capabilities.extensions``
    ``io.modelcontextprotocol/tasks``). Probe failure -> treated as "no support"; never
    raises into the tool.
    """
    try:
        from mcp.types import ClientCapabilities

        session = ctx.session
        # The installed SDK carries the experimental tasks capability under ``experimental``.
        cap = ClientCapabilities(experimental={"io.modelcontextprotocol/tasks": {}})
        return bool(session.check_client_capability(cap))
    except Exception:  # noqa: BLE001 - capability probe must never raise into the tool
        return False


def map_execution_status_to_task_status(status: str | None) -> str:
    """Map one AgentExecution status to an MCP TaskStatus (default ``working``)."""
    if not status:
        return "working"
    return _EXECUTION_TO_TASK_STATUS.get(status, "working")


def derive_aggregate_task_status(counts: dict[str, Any]) -> tuple[str, str]:
    """Reduce a project-level workflow-status count payload to (TaskStatus, statusMessage).

    Approximation for the project surface (the GA per-JOB mapping is exact). Keys come from
    ``get_workflow_status``: active/completed/blocked/closed/silent/decommissioned/pending.
    """

    def _n(key: str) -> int:
        try:
            return int(counts.get(key, 0) or 0)
        except (TypeError, ValueError):
            return 0

    active, pending, blocked = _n("active"), _n("pending"), _n("blocked")
    completed, closed, decommissioned = _n("completed"), _n("closed"), _n("decommissioned")
    silent = _n("silent")
    total = active + pending + blocked + completed + closed + decommissioned + silent

    msg = (
        f"active={active} pending={pending} blocked={blocked} completed={completed} "
        f"closed={closed} decommissioned={decommissioned} silent={silent}"
    )

    if total == 0:
        return "working", "no agents yet"
    if active > 0 or pending > 0 or silent > 0:
        return "working", msg
    if blocked > 0:
        return "working", f"blocked (non-terminal): {msg}"
    if completed > 0 and (completed + closed + decommissioned) == total:
        return "completed", msg
    return "working", msg


def build_task_view(
    task_id: str,
    task_status: str,
    *,
    status_message: str | None,
    created_at: datetime,
    last_updated_at: datetime,
    ttl_ms: int = _DEFAULT_TTL_MS,
    poll_interval_ms: int | None = _DEFAULT_POLL_INTERVAL_MS,
) -> dict[str, Any]:
    """Build a Tasks-shaped view, validated against the installed SDK's ``Task`` type.

    Returns a plain dict (the ``CreateTaskResult`` payload) tagged as a prototype. Note: the
    1.27.2 ``CreateTaskResult`` has no ``resultType`` (pre-SEP-2663); GA adds it.
    """
    from mcp.types import CreateTaskResult, Task

    task = Task(
        taskId=task_id,
        status=task_status,
        statusMessage=status_message,
        createdAt=created_at,
        lastUpdatedAt=last_updated_at,
        ttl=ttl_ms,
        pollInterval=poll_interval_ms,
    )
    return {
        "create_task_result": CreateTaskResult(task=task).model_dump(mode="json"),
        "prototype": True,
        "spec_note": (
            "Prototype (NO-SHIP-UNTIL-GA): demonstrates the our-lifecycle -> MCP Tasks "
            "mapping. Production tasks/get|update + persistent TaskStore land with the GA SDK."
        ),
    }


def maybe_attach_task_view(
    ctx: Context | None,
    result: Any,
    *,
    task_id: str,
    created_at: datetime,
    last_updated_at: datetime,
) -> Any:
    """Attach a ``task_view`` to a ``get_workflow_status`` result when enabled + supported.

    Returns ``result`` unchanged on any miss (flag off, no ctx, no capability, non-dict
    result). Never raises into the tool.
    """
    if ctx is None or not _tasks_prototype_enabled():
        return result
    if not isinstance(result, dict):
        return result
    if not _client_supports_tasks(ctx):
        return result
    try:
        task_status, status_message = derive_aggregate_task_status(result)
        view = build_task_view(
            task_id,
            task_status,
            status_message=status_message,
            created_at=created_at,
            last_updated_at=last_updated_at,
        )
    except Exception:  # noqa: BLE001 - prototype overlay must never break the live tool
        logger.warning("task-view build failed; returning result unchanged", exc_info=True)
        return result
    return {**result, "task_view": view}
