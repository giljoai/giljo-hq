# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

_BOOT_ETAG_PROMISE = "on a match the server omits"
_STEP5_INSTRUCTION = "call get_job_mission ONCE, WITHOUT your boot\n   protocol_etag"


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(result.content[0].text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


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
    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant_key, db_session
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _call(client, tool: str, args: dict) -> dict:
    async with client() as session:
        result = await session.call_tool(tool, args)
    assert result.is_error is False, _error_text(result)
    return _payload(result)


async def _seed_project(db_session, tenant_key: str) -> str:
    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(product)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Chain member {uuid.uuid4().hex[:8]}",
        description="chain member",
        mission="build it",
        status="active",
        staging_status="staging",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="multi_terminal",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project.id


async def _seed_job(db_session, tenant_key: str, project_id: str, job_type: str, phase: str) -> str:
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=job_type,
        mission="chain member work",
        status="active",
        created_at=datetime.now(UTC),
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=str(uuid.uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name=job_type,
            status="working",
            started_at=datetime.now(UTC) - timedelta(minutes=1),
            project_phase=phase,
        )
    )
    await db_session.flush()
    return job.job_id


async def test_implementation_fetch_honours_what_the_staging_protocol_promises(mcp_client):
    client, tenant_key, db_session = mcp_client
    suffix = uuid.uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    await db_session.flush()
    first = await _seed_project(db_session, tenant_key)
    second = await _seed_project(db_session, tenant_key)
    await db_session.commit()

    await _call(client, "link_projects", {"project_ids": [first, second], "execution_mode": "multi_terminal"})
    job_id = await _seed_job(db_session, tenant_key, first, "orchestrator", "staging")
    await _seed_job(db_session, tenant_key, first, "implementer", "implementation")
    await db_session.commit()

    boot = await _call(client, "get_job_mission", {"job_id": job_id})
    assert boot["project_phase"] == "staging"
    boot_etag = boot["protocol_etag"]

    await _call(client, "complete_job", {"job_id": job_id, "result": {"summary": "staging complete"}})
    project = (
        await db_session.execute(select(Project).where(Project.id == first, Project.tenant_key == tenant_key))
    ).scalar_one()
    assert project.implementation_launched_at is not None

    boot_steps = "\n".join(boot["next_required_actions"])
    assert _BOOT_ETAG_PROMISE not in boot["full_protocol"]
    assert "passing the protocol_etag" not in boot_steps
    assert _STEP5_INSTRUCTION in boot["full_protocol"]
    assert "without this response's protocol_etag" in boot_steps

    impl = await _call(client, "get_job_mission", {"job_id": job_id, "protocol_etag": boot_etag})
    assert impl["project_phase"] == "implementation"
    assert impl.get("protocol_unchanged") is not True
    assert impl["protocol_etag"] != boot_etag
    assert "THE COORDINATION LOOP" in impl["full_protocol"]
    assert "Closeout steps (order matters):" in impl["full_protocol"]

    refetch = await _call(client, "get_job_mission", {"job_id": job_id, "protocol_etag": impl["protocol_etag"]})
    assert refetch["protocol_unchanged"] is True, "the NEW etag the protocol says to keep must skip a later refetch"
    assert refetch["full_protocol"] is None
