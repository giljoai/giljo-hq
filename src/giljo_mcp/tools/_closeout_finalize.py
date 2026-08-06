# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Project-row finalization for the MCP closeout path.

Extracted verbatim from ``project_closeout.py`` (BE-9343) when that module crossed
the 800-line guardrail. This is the cohesive piece: everything that decides what the
closeout writes back to the PROJECT ROW and which WebSocket manager carries the
resulting broadcast — as distinct from input validation, git-commit resolution, the
360-memory entry, and the agent-readiness gate, which stay in the parent module.

A pure move: no behaviour change rode along with the extraction. Sits alongside the
existing ``_closeout_metrics`` / ``_memory_helpers`` sibling helpers and follows the
same convention (leading underscore = internal to the closeout tool).
"""

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import DatabaseManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.services.project_helpers import mark_chain_member_status
from giljo_mcp.tenant import TenantManager


logger = logging.getLogger(__name__)


def _resolve_closeout_websocket_manager(explicit: Any | None) -> Any | None:
    """Resolve the WS manager for the MCP closeout broadcasts (BE-6198 live-update).

    Prefers an explicitly-threaded manager (the @mcp.tool boundary passes the
    accessor-held ``_websocket_manager``); otherwise falls back to the registered
    global. Best-effort: a missing registry yields None so the closeout still
    succeeds when WS is unavailable. Mirrors the pattern in
    ``_memory_helpers.emit_websocket_event``.
    """
    if explicit is not None:
        return explicit
    try:
        from giljo_mcp.app_registry.service_registry import get_websocket_manager

        return get_websocket_manager()
    except Exception:  # noqa: BLE001 — WS resolution is best-effort; closeout must not depend on it
        return None


async def _finalize_chain_member_closeout(
    *,
    session: AsyncSession,
    project: Any,
    project_id: str,
    tenant_key: str,
    db_manager: DatabaseManager | None,
    websocket_manager: Any | None,
) -> tuple[Any | None, bool]:
    """Stamp chain-advance signals and finalize a chain-member project row (BE-6198 / BUG #7).

    BE-6198: this MCP closeout path previously wrote ONLY the 360 memory +
    decommissioned agents, leaving project_closeout_at NULL and the run record
    untouched (C1 guard -> CONDUCTOR_CHAIN_INCOMPLETE), which stranded every chain
    at the finish line. So we stamp ``closeout_executed_at`` (the signal the
    conductor's drive loop watches) and mark the chain member 'completed'.

    BUG #7 / BE-6198 (Item B): chain members close headlessly (no user "archive"
    press), so ONLY for an active-run member we flip the project ROW to
    COMPLETED/TERMINATED in the same transaction and broadcast ``project_update`` --
    mirroring the solo archive path so the "Project Completed and Closed" chip
    lights up. Solo projects (is_chain_member False) keep that behaviour: no row
    flip, no extra broadcast (their archive path already emits; gating on
    is_chain_member avoids a double-emit). closeout_executed_at is inert for solo
    and mark_chain_member_status is a no-op without an active run.

    BE-9343: solo is no longer byte-identical in ONE respect -- an absent
    ``completed_at`` is now stamped for it too (see the ``elif`` below). The
    status flip remains chain-member-only.

    Resolves the WS manager ONCE (without it the chain-drive path builds a
    manager-less SequenceRunService that short-circuits its broadcast) and returns
    it so the caller threads the SAME manager into the post-commit
    ``agent:status_changed`` broadcast.

    Also returns ``is_chain_member`` so the caller can build a response message
    that tells the truth about which row-level thing actually happened -- a chain
    member's status genuinely flipped here; a solo project's did not, and the
    caller needs to know which case it is in to say so.
    """
    project.closeout_executed_at = datetime.now(UTC)
    ws = _resolve_closeout_websocket_manager(websocket_manager)
    is_chain_member = await mark_chain_member_status(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        project_id=project_id,
        tenant_key=tenant_key,
        status="completed",
        test_session=session,
        websocket_manager=ws,
    )

    if is_chain_member:
        project.status = ProjectStatus.TERMINATED if project.early_termination else ProjectStatus.COMPLETED
        project.completed_at = datetime.now(UTC)
        await session.flush()

        if ws is not None:
            try:
                await ws.broadcast_project_update(
                    project_id=project_id,
                    update_type="status_changed",
                    project_data={
                        "name": project.name,
                        "status": project.status.value if hasattr(project.status, "value") else project.status,
                        "mission": project.mission,
                    },
                    tenant_key=tenant_key,
                )
            except Exception as ws_error:  # noqa: BLE001 — WS resilience: never fail the closeout
                logger.warning("project_update broadcast failed during chain closeout: %s", ws_error)

    elif project.completed_at is None:
        # BE-9343: a SOLO project closed by an agent was left with completed_at
        # NULL -- the stamp above sat inside the chain-member branch, so a
        # standalone project depended on someone later pressing Archive to get a
        # completion date at all, and if nobody did, the row stayed NULL forever.
        # Closeout IS the completion event here (it writes the 360 memory and
        # decommissions the agents), so it fills the date.
        #
        # Deliberately NOT flipping the status: BUG #7 kept the solo row's status
        # for the user's archive press, and that behaviour is unchanged. Only the
        # missing timestamp is filled, and only when absent.
        #
        # No flush here, matching closeout_executed_at above: the assignment rides
        # the enclosing transaction and is written at commit. The chain branch
        # flushes only because it broadcasts the new row state immediately after.
        project.completed_at = datetime.now(UTC)

    return ws, is_chain_member
