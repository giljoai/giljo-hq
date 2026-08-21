# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Mission-time Hub thread resolution + structural enrolment (TSK-9459).

``get_agent_mission`` resolves the project's bound Hub thread so the served
protocol can name it. It used to do that for every job type EXCEPT
``orchestrator`` — which left the orchestrator as the one agent never handed its
own thread id. Its protocol told it to call ``get_thread_history`` against a
``<your coordination thread>`` placeholder it had no way to resolve, so it never
joined, and a directed post aimed at it reached nobody. Its own workers, handed
a real ``join_thread`` call by the same renderer, joined fine.

That is a MECHANISM gap, not a discipline one: a careful orchestrator following
its protocol to the letter still ended up off the thread. So the orchestrator is
joined HERE, structurally, rather than being told to join — never use prose to
enforce what the tool should guarantee.

This lives in its own leaf module rather than in ``mission_service`` because that
file sits against its shrink-only size budget; the seam is also the natural home
for anything else that has to happen to a thread at mission-serve time.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any


if TYPE_CHECKING:  # pragma: no cover - import cycle guard, typing only
    from sqlalchemy.ext.asyncio import AsyncSession

    from giljo_mcp.models.agent_identity import AgentExecution, AgentJob


logger = logging.getLogger(__name__)


async def resolve_and_enrol(
    mission_service: Any,
    session: AsyncSession,
    job: AgentJob,
    execution: AgentExecution,
    tenant_key: str,
) -> str | None:
    """Resolve this job's bound Hub thread and, for an orchestrator, join it.

    Returns the thread id for the protocol render, or None when the job has no
    project or the thread cannot be resolved (the worker body then renders its
    "no coordination thread bound" degradation, exactly as before).

    Enrolment is orchestrator-only: a WORKER is already handed a real
    ``join_thread`` call in its Phase-1 body and joining it here as well would
    change behaviour this fix has no reproduction for. It runs on every mission
    fetch, which is safe because ``join_thread`` is collision-safe — re-joining
    is a no-op, verified rather than assumed in
    ``tests/services/test_tsk9459_orchestrator_joins_own_thread.py``.

    Best-effort throughout, mirroring ``_resolve_comm_thread_id``: neither a
    failed resolve nor a failed join may break mission delivery.
    """
    if not job.project_id:
        return None
    comm_thread_id = await mission_service._resolve_comm_thread_id(session, job, tenant_key)
    if comm_thread_id and job.job_type == "orchestrator":
        await _join(mission_service, session, comm_thread_id, execution, tenant_key)
    return comm_thread_id


async def _join(
    mission_service: Any,
    session: AsyncSession,
    thread_id: str,
    execution: AgentExecution,
    tenant_key: str,
) -> None:
    """Enroll this executor on the thread, on the SAME session as the render."""
    try:
        from giljo_mcp.services.comm_thread_service import CommThreadService

        comm_service = CommThreadService(mission_service.db_manager, mission_service.tenant_manager, session=session)
        await comm_service.join_thread(
            thread_id=thread_id,
            participant_id=str(execution.agent_id),
            display_name=execution.agent_display_name,
            tenant_key=tenant_key,
        )
    except Exception:  # noqa: BLE001 - best-effort; never break mission delivery
        logger.warning(
            "[TSK-9459] comm thread join failed (non-fatal); the orchestrator is not enrolled",
            extra={"thread_id": thread_id, "agent_id": str(execution.agent_id)},
        )
