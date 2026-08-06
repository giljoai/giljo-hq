# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6209b: get_agent_mission surfaces the LIVE project phase, not a stale snapshot.

Field report friction #2: during the implementation phase the ``project_phase``
field on the mission payload still read ``"staging"``. Cause: every orchestrator
AgentExecution is minted with ``project_phase="staging"`` (the column is frozen at
creation), and the mission payload read that frozen column directly — so once
implementation launched, the value never updated.

The fix derives ``project_phase`` at read time from the authoritative implementation
gate (``project.implementation_launched_at`` — the same signal the staging→
implementation branch and assert_implementation_ready use) instead of the frozen
column.

These tests pin the behaviour at the service layer (MissionService.get_agent_mission,
via the OrchestrationService facade), using fully-mocked DB sessions (matching the
existing get_agent_mission unit tests). Parallel-safe: no DB, no module-level
mutable state, no ordering deps. CE / tenant-scoped.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.services.orchestration_service import OrchestrationService


_TENANT = "tenant-be6209b"


@pytest.fixture
def mock_db_manager():
    db_manager = MagicMock()
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.refresh = AsyncMock()
    session.add = MagicMock()
    session.info = {}  # tenant_session_context save/restore target
    db_manager.get_session_async = MagicMock(return_value=session)
    return db_manager, session


@pytest.fixture
def orchestration_service(mock_db_manager):
    db_manager, _ = mock_db_manager
    return OrchestrationService(db_manager=db_manager, tenant_manager=MagicMock())


def _orchestrator_job_execution(frozen_phase: str = "staging"):
    """Orchestrator job + execution whose project_phase column is frozen at staging
    (the realistic state — every orchestrator execution is minted 'staging')."""
    job_id = str(uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=_TENANT,
        project_id=str(uuid4()),
        mission="Coordinate the work",
        job_type="orchestrator",
        status="active",
    )
    execution = AgentExecution(
        job_id=job_id,
        tenant_key=_TENANT,
        agent_display_name="orchestrator",
        agent_name="orchestrator-1",
        status="working",
        project_phase=frozen_phase,
        mission_acknowledged_at=None,
        started_at=None,
    )
    return job, execution


def _wire_session(session, job, execution, *, implementation_launched_at):
    """Wire the mocked session to answer get_agent_mission's queries, with a project
    whose implementation_launched_at the caller controls (the gate signal)."""
    project = SimpleNamespace(
        id=job.project_id,
        tenant_key=job.tenant_key,
        execution_mode="multi_terminal",
        auto_checkin_enabled=True,
        auto_checkin_interval=15,
        staging_status="staging_complete" if implementation_launched_at else "staging",
        implementation_launched_at=implementation_launched_at,
    )

    job_result = MagicMock()
    job_result.scalar_one_or_none = MagicMock(return_value=job)
    exec_result = MagicMock()
    exec_result.scalar_one_or_none = MagicMock(return_value=execution)
    project_result = MagicMock()
    project_result.scalar_one_or_none = MagicMock(return_value=project)
    all_exec_result = MagicMock()
    all_exec_result.all = MagicMock(return_value=[(execution, job)])

    ordered = [job_result, exec_result, project_result, all_exec_result]
    idx = {"n": 0}

    def _next_result(*_a, **_kw):
        i = idx["n"]
        idx["n"] += 1
        if i < len(ordered):
            return ordered[i]
        empty = MagicMock()
        empty.scalar_one_or_none = MagicMock(return_value=None)
        empty.all = MagicMock(return_value=[])
        empty.scalars = MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        return empty

    session.execute = AsyncMock(side_effect=_next_result)
    return project


@pytest.mark.asyncio
async def test_project_phase_reads_implementation_once_launched(orchestration_service, mock_db_manager):
    """Core regression: with the execution frozen at project_phase='staging', once
    implementation has launched the payload must report 'implementation' (the live
    value), not the stale frozen column."""
    _db, session = mock_db_manager
    job, execution = _orchestrator_job_execution(frozen_phase="staging")
    _wire_session(session, job, execution, implementation_launched_at=datetime.now(UTC))

    response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key=_TENANT)

    assert response.project_phase == "implementation"


@pytest.mark.asyncio
async def test_project_phase_reads_staging_before_launch(orchestration_service, mock_db_manager):
    """Before implementation launches the payload reports 'staging'.

    Pre-launch the solo gate would BLOCK an orchestrator, so this mirrors the only
    pre-launch path that surfaces a mission (a chain member) by stubbing the
    chain-member check — isolating the phase derivation under test.
    """
    _db, session = mock_db_manager
    job, execution = _orchestrator_job_execution(frozen_phase="staging")
    _wire_session(session, job, execution, implementation_launched_at=None)
    orchestration_service._mission._is_chain_member = AsyncMock(return_value=True)

    response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key=_TENANT)

    assert response.project_phase == "staging"


@pytest.mark.asyncio
async def test_non_orchestrator_phase_is_none(orchestration_service, mock_db_manager):
    """Worker agents have no phase semantics — project_phase stays None even though
    the execution carries a frozen column value."""
    _db, session = mock_db_manager
    job, execution = _orchestrator_job_execution(frozen_phase="staging")
    job.job_type = "agent"
    execution.agent_display_name = "implementer"
    _wire_session(session, job, execution, implementation_launched_at=datetime.now(UTC))

    response = await orchestration_service.get_agent_mission(job_id=job.job_id, tenant_key=_TENANT)

    assert response.project_phase is None
