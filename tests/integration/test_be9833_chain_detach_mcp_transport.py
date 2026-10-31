# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.exceptions import ResourceNotFoundError
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    tenant = _TenantSwitch(TenantManager.generate_tenant_key())
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant.value
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior
        async with db_manager.get_session_async() as session:
            with tenant_isolation_bypass(session, reason="test teardown: wipe sequence_runs", models=(SequenceRun,)):
                await session.execute(delete(SequenceRun))
            await session.commit()


async def _seed_running_chain(
    db_session, tenant_key: str, *, still_open_member: bool = True, review_policy: str = "auto_close"
) -> dict:
    suffix = uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    product = Product(
        id=str(uuid4()), name=f"Product {suffix}", description="x", tenant_key=tenant_key, is_active=False
    )
    db_session.add(product)
    await db_session.flush()
    ids = []
    member_states = ("completed", "active", "inactive") if still_open_member else ("completed", "active")
    for status in member_states:
        project = Project(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"Member {status} {suffix}",
            description="x",
            mission="x",
            status=status,
            execution_mode="claude_code_cli",
            series_number=next_series_number(),
        )
        db_session.add(project)
        ids.append(project.id)
    await db_session.flush()
    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.create(
        project_ids=ids,
        resolved_order=ids,
        execution_mode="claude_code_cli",
        tenant_key=tenant_key,
        review_policy=review_policy,
    )
    await run_svc.update(
        run_id=run["id"],
        tenant_key=tenant_key,
        status="running",
        current_index=1,
        project_statuses={
            ids[0]: "completed",
            ids[1]: "implementing",
            **({ids[2]: "pending"} if still_open_member else {}),
        },
    )
    await db_session.commit()
    return {"run_id": run["id"], "tail": ids[1], "run_svc": run_svc, "conductor_agent_id": run["conductor_agent_id"]}


async def test_parking_the_tail_member_over_mcp_detaches_it_from_the_running_run(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed_running_chain(db_session, tenant_key)

    async with new_client() as session:
        result = await session.call_tool("update_project", {"project_id": seed["tail"], "status": "parked"})
        assert result.is_error is False, _error_text(result)

        run = await seed["run_svc"].get(run_id=seed["run_id"], tenant_key=tenant_key)
        assert run["project_statuses"][seed["tail"]] == "detached"
        assert run["status"] == "running"

        workflow = await session.call_tool("get_workflow_status", {"project_id": seed["tail"]})
        assert workflow.is_error is False, _error_text(workflow)
        assert _payload(workflow)["ready_to_advance"] is True


async def test_parking_a_launched_member_over_mcp_resets_it_to_prestage_keeping_parked(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed_running_chain(db_session, tenant_key)
    tail = (await db_session.execute(select(Project).where(Project.id == seed["tail"]))).scalar_one()
    tail.staging_status = "staging_complete"
    tail.implementation_launched_at = tail.created_at
    db_session.add(
        AgentJob(
            job_id=str(uuid4()),
            job_type="orchestrator",
            tenant_key=tenant_key,
            project_id=seed["tail"],
            mission="orchestrator mission",
            status="active",
        )
    )
    await db_session.commit()

    async with new_client() as session:
        result = await session.call_tool("update_project", {"project_id": seed["tail"], "status": "parked"})
        assert result.is_error is False, _error_text(result)

    await db_session.refresh(tail)
    assert tail.status == "parked"
    assert tail.mission == ""
    assert tail.staging_status is None
    assert tail.implementation_launched_at is None
    jobs = (await db_session.execute(select(AgentJob).where(AgentJob.project_id == seed["tail"]))).all()
    assert jobs == []


async def test_dropping_the_last_open_member_over_mcp_ends_the_run(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed_running_chain(db_session, tenant_key, still_open_member=False)

    async with new_client() as session:
        result = await session.call_tool("update_project", {"project_id": seed["tail"], "status": "parked"})
        assert result.is_error is False, _error_text(result)

    with pytest.raises(ResourceNotFoundError):
        await seed["run_svc"].get(run_id=seed["run_id"], tenant_key=tenant_key)


async def test_a_live_conductor_gets_a_clean_reply_after_the_run_ended_itself(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed_running_chain(db_session, tenant_key, still_open_member=False)
    conductor = (
        await db_session.execute(
            select(AgentExecution).where(
                AgentExecution.tenant_key == tenant_key, AgentExecution.agent_id == seed["conductor_agent_id"]
            )
        )
    ).scalar_one()
    job_id = conductor.job_id

    async with new_client() as session:
        parked = await session.call_tool("update_project", {"project_id": seed["tail"], "status": "parked"})
        assert parked.is_error is False, _error_text(parked)
        with pytest.raises(ResourceNotFoundError):
            await seed["run_svc"].get(run_id=seed["run_id"], tenant_key=tenant_key)

        await db_session.refresh(conductor)
        job = (await db_session.execute(select(AgentJob).where(AgentJob.job_id == job_id))).scalar_one()
        await db_session.refresh(job)
        assert conductor.status == "decommissioned"
        assert job.status == "cancelled", "no conductor job may be left working once the chain ended"

        progress = await session.call_tool(
            "report_progress", {"job_id": job_id, "todo_items": [{"content": "wrap up", "status": "completed"}]}
        )
        assert progress.is_error is False, _error_text(progress)

        done = await session.call_tool(
            "complete_job", {"job_id": job_id, "result": {"summary": "chain finished by its members"}}
        )
        assert done.is_error is False, _error_text(done)
        assert "has ended" in _payload(done)["message"]
