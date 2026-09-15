# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.auth.dependencies import get_current_active_user, get_db_session
from giljo_mcp.models import User
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


def _parse_content_dict(result) -> dict[str, Any]:
    return json.loads(_content_text(result))




@pytest_asyncio.fixture
async def lifecycle_mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.job_completion_service import JobCompletionService
    from giljo_mcp.tools.project_closeout import close_project_and_update_memory

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    async def _closeout_with_session(tenant_key: str, **kwargs: Any) -> dict[str, Any]:
        return await close_project_and_update_memory(
            tenant_key=tenant_key,
            db_manager=db_manager,
            session=db_session,
            **kwargs,
        )

    accessor.write_project_closeout = _closeout_with_session
    accessor._job_completion_service = JobCompletionService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def _seed_org_product(db_session, tenant_key: str, *, product_active: bool = True):
    suffix = uuid4().hex[:8]
    org = Organization(
        name=f"BE9165 Org {suffix}",
        slug=f"be9165-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"BE9165 Product {suffix}",
        description="BE-9165 closeout deadlock",
        tenant_key=tenant_key,
        is_active=product_active,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    return org, product


async def _seed_project(
    db_session,
    tenant_key: str,
    product_id: str,
    *,
    execution_mode: str | None = None,
    staging_status: str | None = None,
    implementation_launched_at: datetime | None = None,
):
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE9165 Project {uuid4().hex[:8]}",
        description="BE-9165",
        mission="Closeout deadlock regression",
        status="active",
        staging_status=staging_status,
        execution_mode=execution_mode,
        implementation_launched_at=implementation_launched_at,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def _seed_orchestrator(
    db_session,
    tenant_key: str,
    project_id: str,
    *,
    status: str = "waiting",
):
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="BE-9165 orchestrator",
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
        agent_display_name="orchestrator",
        status=status,
        started_at=datetime.now(UTC) - timedelta(minutes=10),
        project_phase="staging",
    )
    db_session.add(execution)
    await db_session.flush()
    return job, execution


async def _seed_specialist(
    db_session,
    tenant_key: str,
    project_id: str,
    orchestrator_agent_id: str,
    *,
    status: str = "complete",
):
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="BE-9165 specialist",
        status="completed" if status == "complete" else "active",
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
        status=status,
        started_at=datetime.now(UTC) - timedelta(minutes=8),
        completed_at=datetime.now(UTC) - timedelta(minutes=1) if status == "complete" else None,
        project_phase="implementation",
        spawned_by=orchestrator_agent_id,
        result={"summary": "work recorded"} if status == "complete" else None,
    )
    db_session.add(execution)
    await db_session.flush()
    return job, execution


_CLOSEOUT_ARGS = {
    "summary": "Work executed outside the dashboard flow; deliverables recorded.",
    "key_outcomes": ["All specialist work completed and recorded"],
    "decisions_made": ["Closed via force after out-of-session execution"],
}


async def _call_closeout(mcp_session, project_id: str, *, force: bool | None) -> Any:
    args: dict[str, Any] = {"project_id": project_id, **_CLOSEOUT_ARGS}
    if force is not None:
        args["force"] = force
    return await mcp_session.call_tool("write_project_closeout", args)




@pytest.mark.asyncio
async def test_force_closeout_decommissions_unstaged_waiting_orchestrator(lifecycle_mcp_client):
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(session, tenant_key, product.id)
    _orch_job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="waiting")
    await session.commit()

    async with client() as mcp_session:
        result = await _call_closeout(mcp_session, project.id, force=True)

    text = _content_text(result)
    assert not result.is_error, f"force=true closeout must succeed on wall 1, got isError: {text!r}"
    parsed = _parse_content_dict(result)
    assert parsed.get("entry_id"), f"closeout must write the 360 entry, got: {parsed!r}"

    await session.refresh(orch_exec)
    assert orch_exec.status == "decommissioned", (
        f"force=true must auto-decommission the 'waiting' orchestrator, still: {orch_exec.status!r}"
    )




@pytest.mark.asyncio
async def test_force_closeout_closes_staged_project_with_all_specialists_complete(lifecycle_mcp_client):
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(
        session,
        tenant_key,
        product.id,
        execution_mode="subagent",
        staging_status="staging_complete",
    )
    _orch_job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="waiting")
    await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="complete")
    await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="complete")
    await session.commit()

    async with client() as mcp_session:
        result = await _call_closeout(mcp_session, project.id, force=True)

    text = _content_text(result)
    assert not result.is_error, f"force=true closeout must succeed on wall 2, got isError: {text!r}"
    parsed = _parse_content_dict(result)
    assert parsed.get("entry_id"), f"closeout must write the 360 entry, got: {parsed!r}"

    await session.refresh(orch_exec)
    assert orch_exec.status == "decommissioned", (
        f"force=true must decommission the staging-parked orchestrator, still: {orch_exec.status!r}"
    )




@pytest.mark.asyncio
async def test_non_forced_closeout_still_blocks_both_states(lifecycle_mcp_client):
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    _org_b, product_b = await _seed_org_product(session, tenant_key, product_active=False)

    project_a = await _seed_project(session, tenant_key, product.id)
    _job_a, orch_a = await _seed_orchestrator(session, tenant_key, project_a.id, status="waiting")

    project_b = await _seed_project(
        session,
        tenant_key,
        product_b.id,
        execution_mode="subagent",
        staging_status="staging_complete",
    )
    _job_b, orch_b = await _seed_orchestrator(session, tenant_key, project_b.id, status="waiting")
    await _seed_specialist(session, tenant_key, project_b.id, orch_b.agent_id, status="complete")
    await session.commit()

    async with client() as mcp_session:
        for project, orch_exec in ((project_a, orch_a), (project_b, orch_b)):
            result = await _call_closeout(mcp_session, project.id, force=None)

            assert not result.is_error, (
                f"non-forced CLOSEOUT_BLOCKED is a Tier-2 content rejection: {_content_text(result)!r}"
            )
            parsed = _parse_content_dict(result)
            assert parsed.get("success") is False, f"non-forced closeout must be rejected, got: {parsed!r}"
            assert parsed.get("error") == "CLOSEOUT_BLOCKED", f"expected CLOSEOUT_BLOCKED, got: {parsed!r}"

            await session.refresh(orch_exec)
            assert orch_exec.status == "waiting", (
                f"non-forced closeout must not touch the orchestrator, got: {orch_exec.status!r}"
            )




@pytest.mark.asyncio
async def test_force_closeout_still_blocked_while_specialist_in_flight(lifecycle_mcp_client):
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(
        session,
        tenant_key,
        product.id,
        execution_mode="subagent",
        staging_status="staging_complete",
    )
    _orch_job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="waiting")
    _spec_job, spec_exec = await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="working")
    await session.commit()

    async with client() as mcp_session:
        result = await _call_closeout(mcp_session, project.id, force=True)

    if result.is_error:
        text = _content_text(result)
        assert "force-close" in text.lower() or "decommission" in text.lower(), (
            f"expected the force-close guard rejection, got: {text!r}"
        )
    else:
        parsed = _parse_content_dict(result)
        assert parsed.get("success") is False, f"in-flight closeout must be rejected, got: {parsed!r}"

    await session.refresh(spec_exec)
    assert spec_exec.status == "working", (
        f"force=true must NOT decommission an in-flight specialist, got: {spec_exec.status!r}"
    )
    await session.refresh(orch_exec)
    assert orch_exec.status == "waiting", (
        f"force=true must NOT decommission the orchestrator while work is in flight, got: {orch_exec.status!r}"
    )




@pytest.mark.asyncio
async def test_staging_finale_with_all_deliverables_recorded_completes_orchestrator(lifecycle_mcp_client):
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(
        session,
        tenant_key,
        product.id,
        execution_mode="subagent",
        staging_status="staged",
    )
    orch_job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="working")
    await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="complete")
    await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="complete")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": orch_job.job_id,
                "result": {"summary": "Retroactive staging finale — all deliverables already recorded."},
            },
        )

    text = _content_text(result)
    assert not result.is_error, f"staging finale complete_job must succeed: {text!r}"

    await session.refresh(orch_exec)
    assert orch_exec.status == "complete", (
        "staging finale with all deliverables recorded must COMPLETE the orchestrator "
        f"(not re-park it at 'waiting'), got: {orch_exec.status!r}"
    )
    await session.refresh(orch_job)
    assert orch_job.status == "completed", f"the orchestrator job must finalize as completed, got: {orch_job.status!r}"


@pytest.mark.asyncio
async def test_genuine_staging_end_with_waiting_specialists_still_parks_orchestrator(lifecycle_mcp_client):
    client, tenant_key, session = lifecycle_mcp_client
    _org, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(
        session,
        tenant_key,
        product.id,
        execution_mode="subagent",
        staging_status="staged",
    )
    orch_job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="working")
    await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="waiting")
    await session.commit()

    async with client() as mcp_session:
        result = await mcp_session.call_tool(
            "complete_job",
            {
                "job_id": orch_job.job_id,
                "result": {"summary": "Staging complete; specialists spawned and waiting."},
            },
        )

    text = _content_text(result)
    assert not result.is_error, f"genuine staging end must succeed: {text!r}"

    await session.refresh(orch_exec)
    assert orch_exec.status == "waiting", (
        f"a genuine staging end must keep parking the orchestrator at 'waiting', got: {orch_exec.status!r}"
    )
    await session.refresh(orch_job)
    assert orch_job.status == "active", (
        f"the orchestrator job must stay 'active' across the human gate, got: {orch_job.status!r}"
    )




def _build_prompts_app(db_session, user: User) -> FastAPI:
    from api.endpoints.prompts import router as prompts_router

    app = FastAPI()
    app.include_router(prompts_router, prefix="/api/prompts")

    async def _override_user() -> User:
        return user

    async def _override_db():
        yield db_session

    app.dependency_overrides[get_current_active_user] = _override_user
    app.dependency_overrides[get_db_session] = _override_db
    return app


@pytest_asyncio.fixture
async def prompts_rest_client(db_session):
    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:6]

    org = Organization(
        name=f"BE9165 REST Org {suffix}",
        slug=f"be9165-rest-{suffix}",
        tenant_key=tenant_key,
        is_active=True,
    )
    db_session.add(org)
    await db_session.flush()

    user = User(
        username=f"be9165_user_{suffix}",
        email=f"be9165_{suffix}@example.com",
        tenant_key=tenant_key,
        role="developer",
        password_hash="hashed_password",
        org_id=org.id,
    )
    db_session.add(user)
    await db_session.flush()

    app = _build_prompts_app(db_session, user)

    def _client() -> AsyncClient:
        return AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver")

    yield _client, tenant_key, db_session


@pytest.mark.asyncio
async def test_implementation_prompt_all_specialists_complete_is_ready_to_close(prompts_rest_client):
    client, tenant_key, session = prompts_rest_client
    _org2, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(
        session,
        tenant_key,
        product.id,
        execution_mode="subagent",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    _orch_job, orch_exec = await _seed_orchestrator(session, tenant_key, project.id, status="waiting")
    await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="complete")
    await _seed_specialist(session, tenant_key, project.id, orch_exec.agent_id, status="complete")
    await session.commit()

    async with client() as http:
        response = await http.get(f"/api/prompts/implementation/{project.id}")

    body = response.json()
    assert response.status_code == 200, (
        f"all-specialists-complete must NOT 400 (wall 3), got {response.status_code}: {body!r}"
    )
    assert body.get("ready_to_close") is True, f"expected the ready-to-close response, got: {body!r}"
    assert "No agent jobs spawned yet" not in body.get("prompt", ""), (
        "the misleading 'No agent jobs spawned yet' message must never surface for completed specialists"
    )
    assert body.get("agent_count") == 2, f"agent_count should report the completed specialists, got: {body!r}"


@pytest.mark.asyncio
async def test_implementation_prompt_zero_spawned_still_400s(prompts_rest_client):
    client, tenant_key, session = prompts_rest_client
    _org2, product = await _seed_org_product(session, tenant_key)
    project = await _seed_project(
        session,
        tenant_key,
        product.id,
        execution_mode="subagent",
        staging_status="staging_complete",
        implementation_launched_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    await _seed_orchestrator(session, tenant_key, project.id, status="waiting")
    await session.commit()

    async with client() as http:
        response = await http.get(f"/api/prompts/implementation/{project.id}")

    assert response.status_code == 400, (
        f"zero-spawn must keep the 400 gate, got {response.status_code}: {response.json()!r}"
    )
