# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import json
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


def _payload(result) -> dict:
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            return json.loads(text)
    raise AssertionError("tool returned no content")


@pytest_asyncio.fixture
async def activation_race_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor, prior_tm, prior_dbm = state.tool_accessor, state.tenant_manager, state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior_accessor, prior_tm, prior_dbm


async def _seed_product(db_manager, tenant_key: str, name: str) -> str:
    product_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(Product(id=product_id, name=name, tenant_key=tenant_key, is_active=False))
        await session.commit()
    return product_id


async def _seed_inactive_project(db_manager, tenant_key: str, product_id: str, name: str, series_number: int) -> str:
    project_id = str(uuid.uuid4())
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=name,
                description="BE-9502b MCP-boundary activation race",
                mission="prove it through the real tool",
                status=ProjectStatus.INACTIVE,
                series_number=series_number,
            )
        )
        await session.commit()
    return project_id


@pytest_asyncio.fixture
async def two_products_two_projects(db_manager, activation_race_client):
    _client, tenant_key = activation_race_client
    product_a = await _seed_product(db_manager, tenant_key, "MCP race Product A")
    product_b = await _seed_product(db_manager, tenant_key, "MCP race Product B")
    project_a = await _seed_inactive_project(db_manager, tenant_key, product_a, "MCP race Project A1", 1)
    project_b = await _seed_inactive_project(db_manager, tenant_key, product_b, "MCP race Project B1", 1)

    yield {
        "tenant_key": tenant_key,
        "product_a": product_a,
        "product_b": product_b,
        "project_a": project_a,
        "project_b": project_b,
    }

    async with db_manager.get_session_async(tenant_key=tenant_key) as cleanup:
        await cleanup.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
        await cleanup.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
        await cleanup.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await cleanup.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await cleanup.commit()


async def _activate_via_mcp(client_factory, project_id: str):
    async with client_factory() as client:
        return await client.call_tool("update_project", {"project_id": project_id, "status": "active"})


@pytest.mark.asyncio
async def test_cross_product_activation_via_mcp_tool_both_succeed(
    db_manager, activation_race_client, two_products_two_projects
):
    client_factory, tenant_key = activation_race_client
    fixture = two_products_two_projects

    result_a, result_b = await asyncio.gather(
        _activate_via_mcp(client_factory, fixture["project_a"]),
        _activate_via_mcp(client_factory, fixture["project_b"]),
    )

    assert result_a.is_error is False, result_a
    assert result_b.is_error is False, result_b

    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        rows = (await verify.execute(select(Project).where(Project.tenant_key == tenant_key))).scalars().all()
    by_id = {p.id: p for p in rows}
    assert by_id[fixture["project_a"]].status == ProjectStatus.ACTIVE
    assert by_id[fixture["project_b"]].status == ProjectStatus.ACTIVE


@pytest.mark.asyncio
async def test_same_product_activation_race_via_mcp_tool_both_succeed(
    db_manager, activation_race_client, two_products_two_projects
):
    client_factory, tenant_key = activation_race_client
    fixture = two_products_two_projects
    product_a = fixture["product_a"]
    project_a1 = fixture["project_a"]
    project_a2 = await _seed_inactive_project(db_manager, tenant_key, product_a, "MCP race Project A2", 2)

    result_1, result_2 = await asyncio.gather(
        _activate_via_mcp(client_factory, project_a1),
        _activate_via_mcp(client_factory, project_a2),
    )

    assert result_1.is_error is False, result_1
    assert result_2.is_error is False, result_2
    body_1, body_2 = _payload(result_1), _payload(result_2)
    assert body_1.get("success", True) is not False, body_1
    assert body_2.get("success", True) is not False, body_2

    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        rows = (
            (
                await verify.execute(
                    select(Project).where(Project.tenant_key == tenant_key, Project.product_id == product_a)
                )
            )
            .scalars()
            .all()
        )
    active_rows = [p for p in rows if p.status == ProjectStatus.ACTIVE]
    assert len(active_rows) == 2, (
        f"ruling 5 amended: N active projects per product is legal; both concurrent "
        f"MCP-boundary activations must persist ACTIVE; got {[(p.id, p.status.value) for p in rows]}"
    )
