# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models import AgentTodoItem
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import ToolAccessor
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session




def _content_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)




@pytest_asyncio.fixture
async def terminal_state_mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.job_completion_service import JobCompletionService
    from giljo_mcp.services.orchestration_agent_state_service import OrchestrationAgentStateService

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._job_completion_service = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    accessor._agent_state_service = OrchestrationAgentStateService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: False)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def _seed_org_product(db_session, tenant_key: str):
    suffix = uuid4().hex[:8]
    org = Organization(
        name=f"BE9292b Org {suffix}",
        slug=f"be9292b-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"BE9292b Product {suffix}",
        description="BE-9292b job terminal states",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    return org, product


async def _seed_project(db_session, tenant_key: str, product_id: str):
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE9292b Project {uuid4().hex[:8]}",
        description="BE-9292b",
        mission="Silent-job terminal state regression",
        status="active",
        execution_mode="subagent",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC) - timedelta(hours=1),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _seed_specialist(db_session, tenant_key: str, project_id: str, *, status: str):
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="BE-9292b specialist",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()

    execution = AgentExecution(
        id=str(uuid4()),
        agent_id=str(uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        agent_name="implementer-backend",
        status=status,
        started_at=datetime.now(UTC) - timedelta(minutes=90),
        project_phase="implementation",
    )
    db_session.add(execution)
    await db_session.flush()
    return job, execution


async def _seed_todo(db_session, tenant_key: str, job_id: str, content: str):
    todo = AgentTodoItem(
        id=str(uuid4()),
        tenant_key=tenant_key,
        job_id=job_id,
        content=content,
        status="in_progress",
        sequence=1,
    )
    db_session.add(todo)
    await db_session.flush()
    return todo


_VERIFIED_RESULT: dict[str, Any] = {
    "summary": "Guard implemented and audited to APPROVE; commits landed before the stall.",
    "commits": ["b17b7901c", "0ad48106a"],
    "artifacts": ["src/giljo_mcp/services/guard.py"],
}




@pytest.mark.asyncio
async def test_close_job_on_silent_execution_names_the_complete_job_recovery(terminal_state_mcp_client):
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("finalize_job", {"job_id": job.job_id})

    text = _content_text(result)
    assert result.is_error, f"finalize_job on a 'silent' execution must still refuse (gate kept), got: {text!r}"
    assert "silent" in text, f"the refusal must name the actual status, got: {text!r}"
    assert "complete_job" in text, (
        "finalize_job's wrong-state refusal must NAME the complete_job recovery for a "
        f"still-completable execution — otherwise the orchestrator's only visible exit is "
        f"force-decommission. Got: {text!r}"
    )

    await session.refresh(execution)
    assert execution.status == "silent", (
        f"a refused finalize_job must not mutate the execution, got: {execution.status!r}"
    )




@pytest.mark.asyncio
async def test_silent_job_with_verified_deliverable_reaches_closed_not_decommissioned(terminal_state_mcp_client):
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await session.commit()

    async with client() as mcp_session:
        complete_result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": _VERIFIED_RESULT},
        )
        complete_text = _content_text(complete_result)
        assert not complete_result.is_error, (
            f"complete_job must accept a 'silent' execution ('silent' is not terminal), got: {complete_text!r}"
        )

        close_result = await mcp_session.call_tool("finalize_job", {"job_id": job.job_id})
        close_text = _content_text(close_result)
        assert not close_result.is_error, f"finalize_job must accept the now-complete execution, got: {close_text!r}"

    await session.refresh(execution)
    assert execution.status == "closed", (
        f"a stalled-but-successful agent must reach the ACCEPTING terminal state, got: {execution.status!r}"
    )
    assert execution.status != "decommissioned", "an audited, committed contributor must never be labelled a failure"
    assert execution.result == _VERIFIED_RESULT, (
        f"the verified deliverable must be recorded on the execution row, got: {execution.result!r}"
    )




@pytest.mark.asyncio
async def test_close_job_on_decommissioned_execution_does_not_offer_complete_job_recovery(terminal_state_mcp_client):
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, _execution = await _seed_specialist(session, tenant_key, project.id, status="decommissioned")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("finalize_job", {"job_id": job.job_id})

    text = _content_text(result)
    assert result.is_error, f"finalize_job on a decommissioned execution must refuse, got: {text!r}"
    assert "complete_job" not in text, (
        "a decommissioned execution cannot be recovered by complete_job — offering it "
        f"would be a second dead end. Got: {text!r}"
    )




@pytest.mark.asyncio
async def test_close_job_on_working_execution_does_not_offer_complete_job_recovery(terminal_state_mcp_client):
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, _execution = await _seed_specialist(session, tenant_key, project.id, status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool("finalize_job", {"job_id": job.job_id})

    text = _content_text(result)
    assert result.is_error, f"finalize_job on a 'working' execution must refuse, got: {text!r}"
    assert "complete_job" not in text, (
        f"a live 'working' agent must NOT be offered the complete-it-yourself recovery, got: {text!r}"
    )
    assert "diagnose_project_state" in text, f"a reachable agent keeps the generic guidance, got: {text!r}"




@pytest.mark.asyncio
async def test_silent_job_with_stranded_todos_is_completion_blocked_naming_the_todos(terminal_state_mcp_client):
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await _seed_todo(session, tenant_key, job.job_id, "Wire the guard into the service layer")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": _VERIFIED_RESULT},
        )

    text = _content_text(result)
    assert result.is_error, f"an incomplete TODO must still block complete_job on a silent job, got: {text!r}"
    assert "COMPLETION_BLOCKED" in text, f"the rejection must carry the COMPLETION_BLOCKED code, got: {text!r}"
    assert "Wire the guard into the service layer" in text, (
        f"the rejection must name the stranded TODO so the orchestrator can settle it, got: {text!r}"
    )

    await session.refresh(execution)
    assert execution.status == "silent", (
        f"a blocked complete_job must not mutate the execution, got: {execution.status!r}"
    )




@pytest.mark.asyncio
async def test_completion_blocked_names_report_progress_and_speaks_to_the_orchestrator(
    terminal_state_mcp_client,
):
    client, tenant_key, session = terminal_state_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    job, _execution = await _seed_specialist(session, tenant_key, project.id, status="silent")
    await _seed_todo(session, tenant_key, job.job_id, "Wire the guard into the service layer")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {"job_id": job.job_id, "result": _VERIFIED_RESULT},
        )

    text = _content_text(result)
    assert result.is_error, f"an incomplete TODO must still block complete_job, got: {text!r}"
    assert "report_progress" in text, f"COMPLETION_BLOCKED must name the tool that settles the ledger, got: {text!r}"
    assert "replace" in text, (
        "replace=true is the load-bearing argument — without it the orchestrator cannot "
        f"rewrite a stalled agent's ledger to its honest final state. Got: {text!r}"
    )
    assert "your coordination thread" not in text, (
        f"COMPLETION_BLOCKED must not address the caller as the agent whose ledger it is, got: {text!r}"
    )
