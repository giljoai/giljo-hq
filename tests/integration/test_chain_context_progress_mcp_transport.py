# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

_MODE = "claude_code_cli"


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def chain_tenants(db_manager):
    tenants: list[str] = []
    yield tenants
    for tk in tenants:
        async with db_manager.get_session_async(tenant_key=tk) as session:
            await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tk))
            await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tk))
            await session.execute(delete(CommThread).where(CommThread.tenant_key == tk))
            await session.execute(delete(SequenceRun).where(SequenceRun.tenant_key == tk))
            await session.execute(delete(Project).where(Project.tenant_key == tk))
            await session.execute(delete(Product).where(Product.tenant_key == tk))
            await session.commit()


@pytest_asyncio.fixture
async def context_mcp_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    tenant_switch = _TenantSwitch("")
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant_switch
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _seed_two_linked_projects(db_manager, tenant_key: str) -> tuple[str, str, str]:
    product_id, p1, p2 = (str(uuid.uuid4()) for _ in range(3))
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, tenant_key=tenant_key, name="Chain Progress Product"))
        for pid in (p1, p2):
            session.add(
                Project(
                    id=pid,
                    product_id=product_id,
                    name=f"Chain Progress {pid[:8]}",
                    description="chain progress",
                    mission="chain progress",
                    status="completed",
                    tenant_key=tenant_key,
                    execution_mode=_MODE,
                    series_number=random.randint(1, 9000),
                )
            )
        await session.commit()

    svc = SequenceRunService(db_manager=db_manager)
    run = await svc.create(
        project_ids=[p1, p2],
        resolved_order=[p1, p2],
        execution_mode=_MODE,
        status="running",
        project_statuses={p1: "pending", p2: "pending"},
        tenant_key=tenant_key,
    )
    await svc.update(
        run_id=run["id"],
        tenant_key=tenant_key,
        current_index=1,
        project_statuses={p1: "completed", p2: "implementing"},
    )
    return run["id"], p1, p2


async def test_chain_category_returns_run_progress_over_mcp(db_manager, context_mcp_client, chain_tenants) -> None:
    new_client, tenant_switch = context_mcp_client
    tenant = TenantManager.generate_tenant_key()
    chain_tenants.append(tenant)
    tenant_switch.value = tenant
    run_id, p1, p2 = await _seed_two_linked_projects(db_manager, tenant)

    async with new_client() as client:
        result = await client.call_tool("get_context", {"project_id": p2, "categories": ["chain"]})

    assert not result.is_error, result.content
    chain = _payload(result)["data"]["chain"]
    assert chain["run_id"] == run_id
    assert chain["resolved_order"] == [p1, p2]
    assert chain["current_index"] == 1
    assert chain["project_statuses"] == {p1: "completed", p2: "implementing"}


async def test_chain_category_progress_is_tenant_scoped_over_mcp(db_manager, context_mcp_client, chain_tenants) -> None:
    new_client, tenant_switch = context_mcp_client
    owner = TenantManager.generate_tenant_key()
    chain_tenants.append(owner)
    _run_id, _p1, p2 = await _seed_two_linked_projects(db_manager, owner)

    tenant_switch.value = TenantManager.generate_tenant_key()
    async with new_client() as client:
        result = await client.call_tool("get_context", {"project_id": p2, "categories": ["chain"]})

    body = json.dumps([getattr(block, "text", "") for block in result.content])
    assert "implementing" not in body
    assert "current_index" not in body
