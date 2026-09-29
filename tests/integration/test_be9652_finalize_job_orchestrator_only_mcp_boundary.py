# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


def _content_text(result) -> str:
    return "\n".join(getattr(block, "text", "") or "" for block in result.content or [])


def _payload(result) -> dict:
    return json.loads(_content_text(result))


@pytest_asyncio.fixture
async def finalize_mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.job_completion_service import JobCompletionService
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._job_completion_service = JobCompletionService(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    accessor._agent_state_service = OrchestrationAgentStateService(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: False)

    try:
        yield (lambda: create_connected_server_and_client_session(mcp)), tenant_key, db_session
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _seed_project(session, tenant_key: str) -> Project:
    suffix = uuid4().hex[:8]
    session.add(Organization(name=f"BE9652 {suffix}", slug=f"be9652-{suffix}", tenant_key=tenant_key, is_active=True))
    product = Product(
        id=str(uuid4()), name=f"BE9652 {suffix}", tenant_key=tenant_key, is_active=True, product_memory={}
    )
    session.add(product)
    await session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE9652 Project {suffix}",
        description="BE-9652",
        mission="finalize_job orchestrator-only",
        status="active",
        execution_mode="subagent",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC) - timedelta(hours=1),
        series_number=random.randint(1, 9000),
    )
    session.add(project)
    await session.flush()
    return project


async def _seed_job(session, tenant_key: str, project_id: str, *, job_type: str, status: str) -> AgentExecution:
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission="BE-9652",
        status="active",
        created_at=datetime.now(UTC),
    )
    session.add(job)
    await session.flush()
    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=job_type,
        agent_name=job_type,
        status=status,
        started_at=None if status == "waiting" else datetime.now(UTC) - timedelta(minutes=30),
        project_phase="implementation",
    )
    session.add(execution)
    await session.flush()
    return execution


@pytest.mark.asyncio
async def test_worker_cannot_finalize_its_own_job(finalize_mcp_client):
    client, tenant_key, session = finalize_mcp_client
    project = await _seed_project(session, tenant_key)
    worker = await _seed_job(session, tenant_key, project.id, job_type="implementer", status="complete")
    await session.commit()

    async with client() as mcp_session:
        bare = await mcp_session.call_tool("finalize_job", {"job_id": worker.job_id})
        self_named = await mcp_session.call_tool(
            "finalize_job", {"job_id": worker.job_id, "caller_job_id": worker.job_id}
        )

    for result in (bare, self_named):
        assert not result.is_error, f"a refusal is a Tier-2 response, not an error: {_content_text(result)!r}"
        payload = _payload(result)
        assert payload["success"] is False
        assert payload["error"] == "ORCHESTRATOR_ONLY", payload
        assert "complete_job" in payload["message"], payload

    await session.refresh(worker)
    assert worker.status == "complete", f"a refused finalize_job must not seal the job, got {worker.status!r}"


@pytest.mark.asyncio
async def test_orchestrator_of_another_project_cannot_finalize(finalize_mcp_client):
    client, tenant_key, session = finalize_mcp_client
    project = await _seed_project(session, tenant_key)
    other = await _seed_project(session, tenant_key)
    worker = await _seed_job(session, tenant_key, project.id, job_type="implementer", status="complete")
    foreign_orch = await _seed_job(session, tenant_key, other.id, job_type="orchestrator", status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "finalize_job", {"job_id": worker.job_id, "caller_job_id": foreign_orch.job_id}
        )

    assert _payload(result)["error"] == "ORCHESTRATOR_ONLY"
    await session.refresh(worker)
    assert worker.status == "complete"


@pytest.mark.asyncio
async def test_project_orchestrator_finalizes_the_worker(finalize_mcp_client):
    client, tenant_key, session = finalize_mcp_client
    project = await _seed_project(session, tenant_key)
    worker = await _seed_job(session, tenant_key, project.id, job_type="implementer", status="complete")
    orch = await _seed_job(session, tenant_key, project.id, job_type="orchestrator", status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("finalize_job", {"job_id": worker.job_id, "caller_job_id": orch.job_id})

    assert not result.is_error, _content_text(result)
    assert _payload(result).get("success") is not False, _content_text(result)
    await session.refresh(worker)
    assert worker.status == "closed"


@pytest.mark.asyncio
async def test_complete_job_on_a_never_started_worker_job_warns(finalize_mcp_client):
    client, tenant_key, session = finalize_mcp_client
    project = await _seed_project(session, tenant_key)
    worker = await _seed_job(session, tenant_key, project.id, job_type="implementer", status="waiting")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job", {"job_id": worker.job_id, "result": {"summary": "verified on its behalf"}}
        )

    assert not result.is_error, _content_text(result)
    payload = _payload(result)
    assert any("never started" in w for w in payload.get("warnings", [])), payload
    await session.refresh(worker)
    assert worker.status == "complete"


@pytest.mark.asyncio
async def test_complete_job_on_a_started_worker_job_does_not_warn(finalize_mcp_client):
    client, tenant_key, session = finalize_mcp_client
    project = await _seed_project(session, tenant_key)
    worker = await _seed_job(session, tenant_key, project.id, job_type="implementer", status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("complete_job", {"job_id": worker.job_id, "result": {"summary": "done"}})

    assert not result.is_error, _content_text(result)
    assert not any("never started" in w for w in _payload(result).get("warnings", []))
