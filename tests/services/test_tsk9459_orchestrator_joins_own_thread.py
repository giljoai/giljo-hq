# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""TSK-9459 — the orchestrator must be a participant in its own coordination thread.

The defect, as the operator reported it: an orchestrator hands its workers
"join the message hub" instructions but never lands on the hub itself, so a
directed post aimed at the orchestrator reaches nobody.

It was a MECHANISM gap, not a discipline one. ``mission_service`` resolved the
project's bound Hub thread for every job type EXCEPT ``orchestrator``
(``if job.project_id and job.job_type != "orchestrator"``), so the orchestrator
was never given its own thread id — its served protocol asked it to call
``get_thread_history(thread_id=<your coordination thread>, ...)`` against a
placeholder. No amount of care on the agent's side could close that.

The fix joins the orchestrator structurally at mission-serve time rather than
adding another line of instruction. These tests pin the observable:

- the orchestrator's ``agent_id`` is a participant of the project's bound thread
  after ``get_agent_mission`` — the same call the UI-driven path makes when the
  user clicks Implement;
- the served orchestrator protocol carries the REAL thread id, not a placeholder;
- re-serving the mission does not duplicate the participant row (``join_thread``
  is documented collision-safe — verified here, not assumed);
- a project-less orchestrator job still serves its mission and joins nothing.

Real DB (rollback-isolated ``db_session``). Reuses BE-6008's seed helpers, the
same way ``test_be6054c_thread_loop_directive.py`` does.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.services.comm_thread_service import CommThreadService
from giljo_mcp.services.job_lifecycle_service import JobLifecycleService
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.unit.test_be6008_staged_agent_mailboxes import (
    _get_execution,
    _seed_project,
    _seed_template,
)


pytestmark = pytest.mark.asyncio


def _mission_service(db_session: AsyncSession) -> MissionService:
    return MissionService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )


def _comm(db_session: AsyncSession) -> CommThreadService:
    return CommThreadService(db_manager=None, tenant_manager=TenantManager(), session=db_session)


async def _seed_orchestrator(session: AsyncSession, tenant_key: str, project_id: str | None) -> tuple[str, str]:
    """Create the orchestrator job + execution exactly as the UI-driven launch does.

    Mirrors ``project_launch_service._spawn_orchestrator``: ``job_type="orchestrator"``,
    a ``waiting`` execution named ``orchestrator``. Returns ``(job_id, agent_id)``.
    """
    job_id = str(uuid.uuid4())
    agent_id = str(uuid.uuid4())
    session.add(
        AgentJob(
            job_id=job_id,
            tenant_key=tenant_key,
            project_id=project_id,
            mission="Coordinate this project end to end.",
            job_type="orchestrator",
            status="active",
        )
    )
    session.add(
        AgentExecution(
            agent_id=agent_id,
            job_id=job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            agent_name="orchestrator",
            status="waiting",
            progress=0,
            health_status="unknown",
        )
    )
    session.info["tenant_key"] = tenant_key
    await session.flush()
    return job_id, agent_id


async def _participant_ids(db_session: AsyncSession, tenant_key: str, thread_id: str) -> list[str]:
    """Every participant_id on the thread — a NAME LIST, never a count."""
    rows = await db_session.execute(
        select(CommParticipant.participant_id).where(
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.thread_id == thread_id,
        )
    )
    return [row[0] for row in rows]


async def _participant_role(
    db_session: AsyncSession, tenant_key: str, thread_id: str, participant_id: str
) -> str | None:
    """The role recorded on one participant row — which WRITER enrolled them."""
    rows = await db_session.execute(
        select(CommParticipant.role).where(
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.thread_id == thread_id,
            CommParticipant.participant_id == participant_id,
        )
    )
    return rows.scalar_one()


async def _bound_thread_id(db_session: AsyncSession, tenant_key: str, project_id: str) -> str:
    thread = await _comm(db_session).resolve_or_create_bound_thread(project_id=project_id, tenant_key=tenant_key)
    return thread["thread_id"]


async def _stage_project_with_orchestrator_and_worker(
    db_session: AsyncSession,
) -> tuple[str, str, str, str, str]:
    """The UI-driven shape: one project, one orchestrator, one spawned worker.

    Returns ``(tenant_key, project_id, orch_job_id, orch_agent_id, worker_agent_id)``.
    """
    tenant_key = TenantManager.generate_tenant_key()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    project_id = await _seed_project(
        db_session, tenant_key, execution_mode="multi_terminal", implementation_launched=True
    )
    await _seed_template(db_session, tenant_key, "implementer")
    orch_job_id, orch_agent_id = await _seed_orchestrator(db_session, tenant_key, project_id)

    lifecycle = JobLifecycleService(
        db_manager=None,  # type: ignore[arg-type]
        tenant_manager=TenantManager(),
        test_session=db_session,
    )
    worker = await lifecycle.spawn_job(
        agent_display_name="implementer",
        agent_name="implementer",
        project_id=project_id,
        tenant_key=tenant_key,
        mission="Implement the feature.",
    )
    worker_execution = await _get_execution(db_session, tenant_key, worker.job_id)
    worker_agent_id = str(worker_execution.agent_id)

    # The worker fetches its mission and OBEYS its served Phase-1 step 2: it is
    # handed the thread id and told to join, so it joins. This is the half of the
    # system that already works, and it is what makes the orchestrator's absence
    # visible rather than the thread simply being empty.
    worker_protocol = (
        await _mission_service(db_session).get_agent_mission(job_id=worker.job_id, tenant_key=tenant_key)
    ).full_protocol or ""
    thread_id = await _bound_thread_id(db_session, tenant_key, project_id)
    assert f'join_thread(thread_id="{thread_id}"' in worker_protocol, (
        "precondition: the server writes the worker's join instruction with the real thread id"
    )
    await _comm(db_session).join_thread(
        thread_id=thread_id,
        participant_id=worker_agent_id,
        display_name="implementer",
        tenant_key=tenant_key,
    )

    return tenant_key, project_id, orch_job_id, orch_agent_id, worker_agent_id


class TestOrchestratorIsOnItsOwnThread:
    """The defect and its fix, at the layer the bug lived: mission_service."""

    async def test_orchestrator_is_a_participant_after_its_mission_is_served(self, db_session):
        """THE regression. Before the fix the orchestrator's agent_id was absent
        from the participant list while its worker's was present."""
        (
            tenant_key,
            project_id,
            orch_job_id,
            orch_agent_id,
            worker_agent_id,
        ) = await _stage_project_with_orchestrator_and_worker(db_session)

        await _mission_service(db_session).get_agent_mission(job_id=orch_job_id, tenant_key=tenant_key)

        thread_id = await _bound_thread_id(db_session, tenant_key, project_id)
        participants = await _participant_ids(db_session, tenant_key, thread_id)
        assert worker_agent_id in participants, "precondition: the worker joined"
        assert orch_agent_id in participants, (
            f"the orchestrator must be a participant in its own coordination thread; participants were {participants}"
        )

        # The mission-serve enrolment must be what put it there — NOT the BE-6141
        # broadcast rescue (``comm_thread_service._auto_enroll_project_roster``), which
        # enrols a project's active agents as a side effect of somebody else
        # broadcasting and stamps them with the literal role "auto-enrolled".
        #
        # This test never posts a message, so that path is unreachable here by
        # construction. Asserting the role anyway makes it unreachable by MEASUREMENT
        # too: a plain membership check would go green if the fix were removed and a
        # broadcast happened to rescue the orchestrator — which is exactly how this
        # defect stayed hidden in production.
        role = await _participant_role(db_session, tenant_key, thread_id, orch_agent_id)
        assert role != "auto-enrolled", (
            "the orchestrator was rescued by the broadcast auto-enroll, not enrolled by the fix under test"
        )

    async def test_served_orchestrator_protocol_carries_the_real_thread_id(self, db_session):
        """Structural join alone is not enough — an orchestrator that cannot name
        its thread still cannot post to it. The served protocol must carry the id,
        not the ``<your coordination thread>`` placeholder."""
        tenant_key, project_id, orch_job_id, _, _ = await _stage_project_with_orchestrator_and_worker(db_session)

        protocol = (
            await _mission_service(db_session).get_agent_mission(job_id=orch_job_id, tenant_key=tenant_key)
        ).full_protocol or ""

        thread_id = await _bound_thread_id(db_session, tenant_key, project_id)
        assert thread_id in protocol, "the orchestrator protocol must name its own coordination thread"

    async def test_re_serving_the_mission_does_not_duplicate_the_participant(self, db_session):
        """DoD item 4: ``join_thread`` is DOCUMENTED collision-safe. Verify it,
        since the fix makes the orchestrator join on every mission fetch."""
        tenant_key, project_id, orch_job_id, orch_agent_id, _ = await _stage_project_with_orchestrator_and_worker(
            db_session
        )
        service = _mission_service(db_session)

        await service.get_agent_mission(job_id=orch_job_id, tenant_key=tenant_key)
        await service.get_agent_mission(job_id=orch_job_id, tenant_key=tenant_key)
        await service.get_agent_mission(job_id=orch_job_id, tenant_key=tenant_key)

        thread_id = await _bound_thread_id(db_session, tenant_key, project_id)
        participants = await _participant_ids(db_session, tenant_key, thread_id)
        assert participants.count(orch_agent_id) == 1, (
            f"re-joining must be a no-op, not a duplicate row; participants were {participants}"
        )

    async def test_project_less_orchestrator_still_gets_its_mission(self, db_session):
        """A project-less orchestrator (the chain conductor shape) has no bound
        thread to join. Serving its mission must not raise."""
        tenant_key = TenantManager.generate_tenant_key()
        with tenant_session_context(db_session, tenant_key):
            await ensure_default_types_seeded(db_session, tenant_key)
        orch_job_id, _ = await _seed_orchestrator(db_session, tenant_key, None)

        response = await _mission_service(db_session).get_agent_mission(job_id=orch_job_id, tenant_key=tenant_key)

        assert response.full_protocol, "a project-less orchestrator still gets its protocol"
