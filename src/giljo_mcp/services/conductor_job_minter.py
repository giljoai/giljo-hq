# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Project-less chain conductor server-side helpers (BE-6184).

The dedicated chain conductor is a PROJECT-LESS orchestrator: it owns NO project,
has its own ``agent_id``, and drives the whole sequence run. This module collects the
small server-side helpers specific to it:

- ``mint_conductor_job``: insert the conductor AgentJob + AgentExecution in the SAME
  transaction that creates the ``sequence_runs`` row, so a run can never exist without
  an addressable conductor (a failed insert rolls the run back; no orphans). The insert
  mirrors the canonical project-less orchestrator seed at ``install.py``. Returns the
  minted identity (not yet broadcast -- see ``broadcast_conductor_created``).
- ``broadcast_conductor_created``: emit ``agent:created`` for a freshly minted
  conductor (BE-9440 Phase 1: the mint previously broadcast nothing, so a new chain
  conductor appeared on no dashboard until a manual refresh). Deliberately separate
  from ``mint_conductor_job`` -- the mint runs inside the caller's nested transaction,
  and TRANSACTION_OWNERSHIP_CONVENTION requires events to emit only after that
  transaction's outer commit (mirrors ``_ensure_orchestrator_fixture``'s
  commit-then-broadcast ordering), so the caller invokes this only once its commit
  has landed.
- ``projectless_conductor_staging_directive``: the STOP-shaped directive returned when a
  project-less conductor mistakenly calls the staging path (it drives via the runtime
  mission path instead).

Factored out of the owning services to keep them under the 800-line guardrail.

Edition Scope: CE.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.base import generate_uuid
from giljo_mcp.schemas.jsonb_validators import validate_agent_job_metadata
from giljo_mcp.utils.log_sanitizer import sanitize


logger = logging.getLogger(__name__)


async def mint_conductor_job(
    session: AsyncSession,
    *,
    tenant_key: str,
    run_id: str,
    conductor_label: str | None = None,
) -> dict[str, str]:
    """Insert the project-less conductor AgentJob + AgentExecution; return its identity.

    Uses the supplied (already tenant-bound) ``session`` so the writes are atomic
    with the caller's run-create transaction; the caller commits once. The job is
    ``project_id=NULL`` so the conductor is symmetric to every sub-orchestrator
    instead of owning the head project (the dual-hat collapse BE-6184 removes).

    ``agent_jobs.project_id`` is nullable (see ``agent_identity.py``), so no
    migration is required. The execution starts in ``project_phase="implementation"``
    (the conductor exists only to drive an in-flight run) and ``status="waiting"`` so
    the agent's first ``get_job_mission`` transitions it to ``working`` exactly like
    any other orchestrator.

    Returns ``{"agent_id", "job_id", "execution_id"}`` -- the caller passes this straight
    to ``broadcast_conductor_created`` once its own commit lands.
    """
    job_id = generate_uuid()
    agent_id = generate_uuid()

    conductor_job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=None,
        mission=None,
        job_type="orchestrator",
        status="active",
        job_metadata=validate_agent_job_metadata({"chain_conductor": True, "run_id": run_id}),
    )
    session.add(conductor_job)

    conductor_execution = AgentExecution(
        agent_id=agent_id,
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        agent_name=conductor_label or "Chain Conductor",
        status="waiting",
        health_status="unknown",
        project_phase="implementation",
    )
    session.add(conductor_execution)

    await session.flush()
    return {"agent_id": agent_id, "job_id": job_id, "execution_id": conductor_execution.id}


async def broadcast_conductor_created(
    websocket_manager: Any | None,
    *,
    tenant_key: str,
    run_id: str,
    agent_id: str,
    job_id: str,
    execution_id: str,
    conductor_label: str | None = None,
) -> None:
    """Broadcast ``agent:created`` for a freshly minted chain conductor (BE-9440 Phase 1).

    Call ONLY after the caller's own transaction has committed (see the module
    docstring). Fire-and-forget: a failed broadcast never fails the mint, mirroring
    every other ``agent:created`` emitter in this codebase.
    """
    if websocket_manager is None:
        return
    try:
        await websocket_manager.broadcast_to_tenant(
            tenant_key=tenant_key,
            event_type="agent:created",
            data={
                "project_id": None,
                "execution_id": execution_id,
                "agent_id": agent_id,
                "job_id": job_id,
                "agent_display_name": "orchestrator",
                "agent_name": conductor_label or "Chain Conductor",
                "status": "waiting",
                "chain_conductor": True,
                "run_id": run_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )
    except Exception as ws_error:  # noqa: BLE001 - WebSocket resilience: non-critical broadcast
        logger.warning(
            "Failed to broadcast agent:created for conductor %s: %s",
            sanitize(agent_id),
            ws_error,
        )


def projectless_conductor_staging_directive(job_id: str) -> dict[str, Any]:
    """STOP-shaped staging directive for the project-less chain conductor (BE-6184).

    The dedicated conductor has no project to stage; it receives its chain-drive
    protocol via the runtime mission path (get_job_mission), not staging. Returned by
    ``get_staging_instructions`` instead of the misleading "Project not found" 404.
    """
    return {
        "status": "CHAIN_CONDUCTOR",
        "action": "USE_RUNTIME_MISSION",
        "redirect": None,
        "identity": {"job_id": job_id, "project_id": None},
        "message": (
            "You are the dedicated chain conductor (no project of your own). There are no "
            "staging instructions for you; call get_job_mission to receive your chain-drive "
            "protocol and advance the run."
        ),
        "thin_client": True,
    }
