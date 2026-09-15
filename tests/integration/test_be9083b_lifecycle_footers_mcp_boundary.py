# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.product_crew_helper import adopt_all_templates


pytestmark = pytest.mark.asyncio




def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))




@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def _seed_project(
    db_session,
    tenant_key: str,
    *,
    implementation_launched: bool,
    staging_status: str,
) -> str:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-9083b", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE-9083b {suffix}",
        description="lifecycle footer cell",
        mission="build it",
        status="active",
        staging_status=staging_status,
        series_number=random.randint(1, 9000),
        execution_mode="multi_terminal",
        implementation_launched_at=now if implementation_launched else None,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    await adopt_all_templates(db_session, tenant_key, product.id)
    return project.id


async def _seed_job(
    db_session,
    tenant_key: str,
    project_id: str,
    *,
    job_type: str,
    agent_display_name: str,
    project_phase: str = "staging",
) -> str:
    now = datetime.now(UTC)
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission="BE-9083b mission",
        status="active",
        created_at=now,
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name=agent_display_name,
        status="working",
        started_at=now - timedelta(minutes=3),
        project_phase=project_phase,
    )
    db_session.add(execution)
    await db_session.commit()
    return job.job_id


async def _seed_template(db_session, tenant_key: str, name: str) -> None:
    db_session.add(AgentTemplate(id=str(uuid.uuid4()), tenant_key=tenant_key, name=name, is_active=True))
    await db_session.commit()
    for (_pid,) in (await db_session.execute(select(Product.id).where(Product.tenant_key == tenant_key))).all():
        await adopt_all_templates(db_session, tenant_key, _pid)


async def _seed_active_run(db_session, tenant_key: str, project_ids: list[str]) -> None:
    db_session.add(
        SequenceRun(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            project_ids=project_ids,
            resolved_order=project_ids,
            current_index=0,
            execution_mode="multi_terminal",
            status="running",
            locked=True,
            conductor_agent_id=str(uuid.uuid4()),
            project_statuses=dict.fromkeys(project_ids, "pending"),
        )
    )
    await db_session.commit()




async def test_spawn_job_staging_footer(mcp_client):
    client, tenant_key, db_session = mcp_client
    project_id = await _seed_project(db_session, tenant_key, implementation_launched=False, staging_status="staging")
    await _seed_template(db_session, tenant_key, "implementer")

    async with client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "implementer",
                "agent_name": "implementer",
                "project_id": project_id,
                "mission": "Implement the thing.",
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    footer = payload["lifecycle_footer"]
    assert "agent:created" in footer
    assert "JobsTab" in footer
    assert "INERT" in footer


async def test_spawn_job_implementation_footer(mcp_client):
    client, tenant_key, db_session = mcp_client
    project_id = await _seed_project(
        db_session, tenant_key, implementation_launched=True, staging_status="staging_complete"
    )
    await _seed_template(db_session, tenant_key, "tester")

    async with client() as session:
        result = await session.call_tool(
            "spawn_job",
            {
                "agent_display_name": "tester",
                "agent_name": "tester",
                "project_id": project_id,
                "mission": "Test the thing.",
            },
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    footer = payload["lifecycle_footer"]
    assert "agent:created" in footer
    assert "ready to launch" in footer
    assert "INERT" not in footer




async def test_update_project_mission_staging_footer(mcp_client):
    client, tenant_key, db_session = mcp_client
    project_id = await _seed_project(db_session, tenant_key, implementation_launched=False, staging_status="staging")

    async with client() as session:
        result = await session.call_tool(
            "update_project_mission",
            {"project_id": project_id, "mission": "The refined project mission."},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    footer = payload["lifecycle_footer"]
    assert "project:mission_updated" in footer
    assert "mission panel" in footer
    assert "spawn_job" in footer




async def test_complete_job_staging_end_solo_footer(mcp_client):
    client, tenant_key, db_session = mcp_client
    project_id = await _seed_project(db_session, tenant_key, implementation_launched=False, staging_status="staging")
    orch_job = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )
    await _seed_job(db_session, tenant_key, project_id, job_type="implementer", agent_display_name="implementer")

    async with client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": orch_job, "result": {"summary": "staging done"}},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["phase"] == "staging_end"
    footer = payload["lifecycle_footer"]
    assert "staging-complete" in footer
    assert "waiting" in footer
    assert "Implement" in footer
    assert "ALREADY advanced" not in footer


async def test_complete_job_staging_end_chain_suborch_footer(mcp_client):
    client, tenant_key, db_session = mcp_client
    project_id = await _seed_project(db_session, tenant_key, implementation_launched=False, staging_status="staging")
    await _seed_active_run(db_session, tenant_key, [project_id])
    orch_job = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )
    await _seed_job(db_session, tenant_key, project_id, job_type="implementer", agent_display_name="implementer")

    async with client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": orch_job, "result": {"summary": "chain staging done"}},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["phase"] == "staging_end"
    footer = payload["lifecycle_footer"]
    assert "CHAIN member" in footer
    assert "ALREADY advanced" in footer
    assert "get_job_mission" in footer
    assert "protocol_etag" in footer


async def test_complete_job_closeout_footer(mcp_client):
    client, tenant_key, db_session = mcp_client
    project_id = await _seed_project(
        db_session, tenant_key, implementation_launched=True, staging_status="staging_complete"
    )
    orch_job = await _seed_job(
        db_session, tenant_key, project_id, job_type="orchestrator", agent_display_name="orchestrator"
    )

    async with client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": orch_job, "result": {"summary": "impl done"}},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["phase"] == "closeout"
    footer = payload["lifecycle_footer"]
    assert "CloseoutModal" in footer
    assert "write_project_closeout" in footer


async def test_complete_job_deliverable_footer(mcp_client):
    client, tenant_key, db_session = mcp_client
    project_id = await _seed_project(
        db_session, tenant_key, implementation_launched=True, staging_status="staging_complete"
    )
    worker_job = await _seed_job(
        db_session, tenant_key, project_id, job_type="implementer", agent_display_name="implementer"
    )

    async with client() as session:
        result = await session.call_tool(
            "complete_job",
            {"job_id": worker_job, "result": {"summary": "deliverable done"}},
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["phase"] == "deliverable"
    footer = payload["lifecycle_footer"]
    assert "complete (green)" in footer
    assert "No further action" in footer
