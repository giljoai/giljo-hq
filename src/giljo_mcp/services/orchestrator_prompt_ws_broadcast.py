# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9332: the single shared emitter for the ``orchestrator:prompt_generated`` WS event.

Before this module the event had TWO hand-inlined emission sites, both inside REST
endpoint bodies in ``api/endpoints/prompts.py`` -- and they had already drifted apart
(one carried ``estimated_tokens`` + ``timestamp``, the other ``agent_id`` + ``tool``;
neither payload was a superset of the other). The MCP ``stage_project`` path had no
site at all, so a CLI-driven staging created the orchestrator, persisted the staged
state, and left the dashboard silent -- the card never appeared.

Rather than add a THIRD uncoordinated writer, the event shape lives here once and every
caller goes through this function. Mirrors the ``closeout_ws_broadcast`` precedent:
module-level (not a method) so callers with no reason to instantiate a service can reuse
the SAME event shape instead of forking a parallel dict.

Contract:
- **No-ops when the manager is absent.** ``websocket_manager=None`` is a normal state
  (an accessor built before the WS manager exists), not an error.
- **Best-effort: never raises.** A failed notification must not fail the staging it is
  reporting on -- same rule every other WS emit in this codebase follows.
- **Optional keys are OMITTED when ``None``, never sent as null.** The frontend store
  merges payload keys onto existing state (``{...previous, ...patch}``), so a stray
  ``None`` would overwrite a good value; omitting the key leaves it untouched. This also
  keeps each caller's wire payload a superset of what it sent before the extraction.
- **Call it POST-COMMIT.** This function does no DB work and has no opinion on
  transaction boundaries, but a broadcast must never announce state a rollback could
  still undo.

Payload consumers: ``frontend/src/stores/eventRoutes/agentEventRoutes.js`` routes this
event to ``agentJobsStore.handleUpdated`` -> ``upsertJob``, which creates the
orchestrator row. The route reads ``orchestrator_id``, ``agent_id``, ``execution_id``
and ``project_id`` off the payload, so all four should be supplied whenever the caller
has them -- that is the field set the BE-9332 anti-drift test pins across call sites.
"""

import logging
from typing import Any


_module_logger = logging.getLogger(__name__)

EVENT_TYPE = "orchestrator:prompt_generated"


async def broadcast_orchestrator_prompt_generated(
    websocket_manager: Any,
    *,
    tenant_key: str,
    project_id: str,
    orchestrator_id: str,
    agent_id: str | None = None,
    execution_id: str | None = None,
    estimated_tokens: int | None = None,
    tool: str | None = None,
    timestamp: str | None = None,
    product_id: str | None = None,  # BE-9518
) -> None:
    """Broadcast ``orchestrator:prompt_generated`` to the calling tenant (BE-9332).

    ``project_id``, ``orchestrator_id`` and ``thin_client`` are always present; every
    other field is included only when the caller supplies it, so a caller's payload is
    exactly what it chose to send. Tenant-scoped by construction -- the event never
    reaches a broader audience than ``tenant_key``.
    """
    if not websocket_manager:
        return

    data: dict[str, Any] = {
        "project_id": project_id,
        "orchestrator_id": orchestrator_id,
        "thin_client": True,
    }
    optional = {
        "agent_id": agent_id,
        "execution_id": execution_id,
        "estimated_tokens": estimated_tokens,
        "tool": tool,
        "timestamp": timestamp,
        "product_id": product_id,  # BE-9518
    }
    data.update({key: value for key, value in optional.items() if value is not None})

    try:
        await websocket_manager.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type=EVENT_TYPE,
            data=data,
        )
    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
        _module_logger.warning(
            "[WEBSOCKET] Failed to broadcast %s for orchestrator %s: %s", EVENT_TYPE, orchestrator_id, ws_error
        )
