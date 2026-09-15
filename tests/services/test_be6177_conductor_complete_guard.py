# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.job_completion_service import JobCompletionService
from giljo_mcp.tenant import TenantManager


pytestmark = pytest.mark.asyncio


class _FakeJob:
    def __init__(self, job_type: str = "orchestrator") -> None:
        self.job_type = job_type


class _FakeExec:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id


async def _seed_run(db_manager, *, conductor_agent_id, project_statuses, resolved_order, status="running") -> str:
    tenant_key = TenantManager.generate_tenant_key()
    async with db_manager.get_session_async() as session:
        run = SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_ids=resolved_order,
            resolved_order=resolved_order,
            current_index=0,
            execution_mode="claude_code_cli",
            status=status,
            locked=True,
            conductor_agent_id=conductor_agent_id,
            project_statuses=project_statuses,
        )
        session.add(run)
        await session.commit()
    return tenant_key


async def _call_guard(db_manager, tenant_key, *, agent_id, job_type="orchestrator") -> None:
    svc = JobCompletionService(db_manager=db_manager, tenant_manager=TenantManager())
    async with db_manager.get_session_async() as session:
        await svc._guard_conductor_chain_incomplete(
            session, _FakeJob(job_type), _FakeExec(agent_id), tenant_key, "job-x"
        )


async def test_conductor_complete_blocked_while_projects_incomplete(db_manager):
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager,
        conductor_agent_id="cond-1",
        project_statuses={p1: "completed", p2: "pending"},
        resolved_order=[p1, p2],
    )
    with pytest.raises(ValidationError) as ei:
        await _call_guard(db_manager, tenant_key, agent_id="cond-1")
    assert ei.value.error_code == "CONDUCTOR_CHAIN_INCOMPLETE"


async def test_conductor_complete_allowed_when_all_projects_done(db_manager):
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager,
        conductor_agent_id="cond-1",
        project_statuses={p1: "completed", p2: "completed"},
        resolved_order=[p1, p2],
    )
    await _call_guard(db_manager, tenant_key, agent_id="cond-1")


async def test_non_conductor_agent_never_blocked(db_manager):
    p1, p2 = str(uuid.uuid4()), str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager,
        conductor_agent_id="cond-1",
        project_statuses={p1: "pending", p2: "pending"},
        resolved_order=[p1, p2],
    )
    await _call_guard(db_manager, tenant_key, agent_id="some-other-agent")


async def test_non_orchestrator_job_never_blocked(db_manager):
    p1 = str(uuid.uuid4())
    tenant_key = await _seed_run(
        db_manager,
        conductor_agent_id="cond-1",
        project_statuses={p1: "pending"},
        resolved_order=[p1],
    )
    await _call_guard(db_manager, tenant_key, agent_id="cond-1", job_type="implementer")
