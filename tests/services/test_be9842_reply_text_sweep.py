# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.project_closeout_readiness import AgentReadinessFinding, shape_agent_blocker
from giljo_mcp.services.project_closeout_service import ProjectCloseoutService
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.services.workflow_status_service import WorkflowStatusService
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.services.test_be9655b_holding_vs_silent import _seed_agent, _seed_project


def _finding(status: str) -> AgentReadinessFinding:
    return AgentReadinessFinding(
        job_id="job-9842",
        agent_id="agent-9842",
        agent_name="impl",
        status=status,
        messages_waiting=0,
        incomplete_todos=[],
        incomplete_pending=0,
        incomplete_in_progress=0,
        awaiting_user=False,
        approval_id=None,
    )


@pytest.mark.asyncio
async def test_create_product_reply_does_not_call_a_shown_product_inactive(db_manager) -> None:
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=TenantManager())
    reply = await accessor.create_product(name=f"BE-9842 {uuid4().hex[:8]}", tenant_key=str(uuid4()))

    assert reply["is_active"] is True
    assert "inactive" not in reply["next_step"]
    assert "activates it" not in reply["next_step"]
    assert "shown" in reply["next_step"]


@pytest.mark.parametrize("status", ["waiting", "staged"])
def test_never_started_worker_blocker_points_at_dismiss_job(status: str) -> None:
    action = shape_agent_blocker(_finding(status))["suggested_action"]

    assert "dismiss_job(job_id='job-9842')" in action
    assert "complete_job" not in action
    assert "Force-complete" not in action


def test_started_worker_blocker_still_advises_complete_job() -> None:
    action = shape_agent_blocker(_finding("working"))["suggested_action"]

    assert "complete_job(job_id='job-9842')" in action


def test_blocked_is_not_described_as_needing_human_help() -> None:
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService
    from giljo_mcp.services.protocol_sections import orchestrator_body

    for source in (inspect.getsource(orchestrator_body), inspect.getsource(OrchestrationAgentStateService)):
        assert "needs human help" not in source


@pytest.mark.asyncio
async def test_diagnose_and_workflow_status_count_the_same_board(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    kw = {"last_progress_minutes_ago": 1}
    await _seed_agent(db_session, tenant, pid, status="working", todo_statuses=["in_progress"], **kw)
    await _seed_agent(db_session, tenant, pid, status="working", todo_statuses=["completed"], **kw)
    await _seed_agent(db_session, tenant, pid, status="waiting", todo_statuses=[], **kw)
    await _seed_agent(db_session, tenant, pid, status="complete", todo_statuses=["completed"], **kw)
    await _seed_agent(db_session, tenant, pid, status="blocked", todo_statuses=["pending"], **kw)

    workflow = await WorkflowStatusService(
        db_manager=None, tenant_manager=TenantManager(), test_session=db_session
    ).get_workflow_status(pid, tenant)
    diagnosis = await ProjectCloseoutService(None, TenantManager(), test_session=db_session).diagnose_project_state(
        pid, tenant
    )
    counts = diagnosis["agent_status_counts"]

    assert counts["total"] == workflow.total_agents == 5
    assert counts["active"] == workflow.active_agents == 1
    assert counts["holding"] == workflow.holding_agents == 1
    assert counts["blocked"] == workflow.blocked_agents == 1
    assert counts["silent"] == workflow.silent_agents == 0
    assert counts["complete"] == workflow.completed_agents == 1


@pytest.mark.asyncio
async def test_sequence_run_refusals_use_the_dashboard_words(db_session: AsyncSession) -> None:
    tenant = TenantManager.generate_tenant_key()
    pid = await _seed_project(db_session, tenant)
    service = SequenceRunService(session=db_session)
    run = await service.create(
        project_ids=[pid],
        resolved_order=[pid],
        execution_mode="claude_code_cli",
        status="running",
        project_statuses={pid: "pending"},
        tenant_key=tenant,
    )

    with pytest.raises(ValidationError) as unstage:
        await service.update(run_id=run["id"], tenant_key=tenant, locked=False)
    with pytest.raises(ValidationError) as membership:
        await service.remove_member(run_id=run["id"], project_id=pid, tenant_key=tenant)

    for refusal in (unstage.value, membership.value):
        assert "Stop chain or Deactivate chain" in refusal.message
        assert "Terminate" not in refusal.message
