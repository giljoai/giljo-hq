# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.taxonomy_seeds import next_series_number


pytestmark = pytest.mark.asyncio


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    return json.loads(res.content[0].text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


async def _seed(db_session, tenant_key: str, *, status: str, mission: str | None) -> str:
    suffix = uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    product = Product(id=str(uuid4()), name=f"Product {suffix}", description="x", tenant_key=tenant_key, is_active=True)
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        staging_status="staging_complete",
        execution_mode="subagent",
        series_number=next_series_number(),
        implementation_launched_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add(project)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="tester",
        mission=mission,
        status="active",
        created_at=datetime.now(UTC) - timedelta(minutes=10),
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        AgentExecution(
            id=str(uuid4()),
            agent_id=str(uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="tester",
            agent_name="tester",
            status=status,
            started_at=datetime.now(UTC) - timedelta(minutes=10),
        )
    )
    await db_session.commit()
    return job.job_id


async def _status(db_session, tenant_key: str, job_id: str) -> str:
    db_session.expire_all()
    return await db_session.scalar(
        select(AgentExecution.status).where(AgentExecution.tenant_key == tenant_key, AgentExecution.job_id == job_id)
    )


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
    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    monkeypatch.setattr(_base, "should_run", lambda *args, **kwargs: False)
    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant_key
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def test_staged_worker_is_started_by_its_first_get_job_mission(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    job_id = await _seed(db_session, tenant_key, status="staged", mission=None)

    async with new_client() as session:
        mission = await session.call_tool("get_job_mission", {"job_id": job_id})
        assert mission.is_error is False, _error_text(mission)
        assert await _status(db_session, tenant_key, job_id) == "working"

        done = await session.call_tool("complete_job", {"job_id": job_id, "result": {"summary": "tested"}})
        assert done.is_error is False, _error_text(done)
        warnings = _payload(done).get("warnings", [])
        assert not any("never started" in w for w in warnings), warnings


async def test_waiting_worker_still_starts_on_first_fetch(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    job_id = await _seed(db_session, tenant_key, status="waiting", mission="Test the thing.")

    async with new_client() as session:
        mission = await session.call_tool("get_job_mission", {"job_id": job_id})
        assert mission.is_error is False, _error_text(mission)
    assert await _status(db_session, tenant_key, job_id) == "working"


async def test_mission_written_after_the_start_does_not_move_the_job_back(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    job_id = await _seed(db_session, tenant_key, status="staged", mission=None)

    async with new_client() as session:
        await session.call_tool("get_job_mission", {"job_id": job_id})
        updated = await session.call_tool("update_job_mission", {"job_id": job_id, "mission": "Test the thing."})
        assert updated.is_error is False, _error_text(updated)
    assert await _status(db_session, tenant_key, job_id) == "working"


async def test_mission_written_before_any_fetch_still_unlocks_staged_to_waiting(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    job_id = await _seed(db_session, tenant_key, status="staged", mission=None)

    async with new_client() as session:
        updated = await session.call_tool("update_job_mission", {"job_id": job_id, "mission": "Test the thing."})
        assert updated.is_error is False, _error_text(updated)
    assert await _status(db_session, tenant_key, job_id) == "waiting"
