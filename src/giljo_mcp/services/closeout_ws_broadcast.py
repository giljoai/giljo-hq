# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9246: shared WebSocket-broadcast unit for closeout agent-status transitions.

Extracted VERBATIM (file-size compliance, behavior identical) from
``orchestration_agent_state_service`` + ``project_closeout_service`` so the
closeout paths -- which have no reason to instantiate a full
``OrchestrationAgentStateService`` -- reuse the SAME ``agent:status_changed``
event shape instead of forking a parallel dict.

Contract (unchanged from the pre-extraction inline code):
- Build the events BEFORE overwriting ``execution.status`` (old_status must be
  the pre-transition value).
- Emit them strictly POST-COMMIT so a broadcast can never announce a status a
  rollback could still undo.
"""

import logging
from collections.abc import Iterable
from typing import Any

from giljo_mcp.models import AgentExecution
from giljo_mcp.schemas.service_responses import AgentStatusChangeEvent


_module_logger = logging.getLogger(__name__)


def build_agent_status_change_events(
    executions: Iterable[AgentExecution],
    new_status: str,
) -> list[AgentStatusChangeEvent]:
    """Build one ``AgentStatusChangeEvent`` per execution for a batch transition.

    Captures each execution's CURRENT ``.status`` as ``old_status`` -- callers
    MUST build the events BEFORE overwriting ``execution.status``, so it records
    the pre-transition value (exactly what the former inline construction did).
    Pure, no I/O; the caller emits the events POST-COMMIT.
    """
    return [
        AgentStatusChangeEvent(
            job_id=execution.job_id,
            agent_id=execution.agent_id,
            agent_display_name=execution.agent_display_name,
            agent_name=execution.agent_name,
            old_status=execution.status,
            new_status=new_status,
        )
        for execution in executions
    ]


async def broadcast_agent_status_changed(
    websocket_manager: Any,
    *,
    tenant_key: str,
    project_id: str | None,
    event: AgentStatusChangeEvent,
) -> None:
    """Broadcast one ``agent:status_changed`` WS event for a status transition (BE-9246).

    Module-level (not a method) so callers outside the orchestration service --
    the project closeout paths, which have no reason to instantiate a full
    ``OrchestrationAgentStateService`` -- can reuse the SAME event shape that
    class's ``_broadcast_completion`` / ``close_job`` already emit, instead of
    forking a parallel dict. Must be called POST-COMMIT by the caller; this
    function does no DB work and has no opinion on transaction boundaries.

    Deliberately a reduced field set relative to ``_broadcast_completion``
    (omits ``chain_conductor``, ``completed_at``, ``duration_seconds``,
    ``working_started_at``, ``has_result``): the closeout batch transitions
    (decommission / complete->closed) scan many executions per project and
    have no cheap per-agent ``AgentJob.job_metadata`` lookup on hand for
    ``chain_conductor`` without an N+1 query, and the frontend store merges
    payload keys onto existing state (``{...previous, ...patch}``) -- a
    stray ``chain_conductor: False`` would silently overwrite a true value,
    whereas simply omitting the key leaves the existing (still-correct)
    value untouched. ``job_id`` + ``status`` are all ``handleStatusChanged``
    requires to update the dashboard tile.

    Best-effort: never raises. A broadcast failure must not fail the
    closeout it is reporting on, mirroring every other WS emit in this file.
    """
    if not websocket_manager:
        return
    try:
        await websocket_manager.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="agent:status_changed",
            data={
                "job_id": event.job_id,
                "project_id": project_id,
                "agent_display_name": event.agent_display_name,
                "agent_name": event.agent_name,
                "old_status": event.old_status,
                "status": event.new_status,
            },
        )
    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
        _module_logger.warning(
            "[WEBSOCKET] Failed to broadcast agent:status_changed for %s: %s", event.job_id, ws_error
        )


async def broadcast_agent_status_events(
    websocket_manager: Any,
    *,
    tenant_key: str,
    project_id: str | None,
    events: Iterable[AgentStatusChangeEvent],
) -> None:
    """Emit ``broadcast_agent_status_changed`` once per event (BE-9246 POST-COMMIT).

    Batch wrapper for the shared post-commit emit loop. Each underlying call
    swallows its own WS failure; must be called AFTER the caller's commit.

    Callers that do NOT own the commit pass an empty ``events`` iterable to
    suppress emission entirely. In ``close_project_and_update_memory`` this
    encodes the owns_session guard: when the caller supplied its own session
    (owns_session=False -- e.g. the REST self-heal complete_project flow),
    commit timing belongs to that caller, so emitting here would announce a
    status a rollback there could still undo. That path therefore passes no
    events and this wrapper broadcasts nothing (unchanged behaviour, just not
    yet covered) -- while the normal owns_session=True MCP-tool path, whose
    ``async with`` session context has already committed, passes the real
    decommission events.
    """
    for event in events:
        await broadcast_agent_status_changed(
            websocket_manager,
            tenant_key=tenant_key,
            project_id=project_id,
            event=event,
        )
