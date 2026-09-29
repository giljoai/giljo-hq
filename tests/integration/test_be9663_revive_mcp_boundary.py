# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


@pytest_asyncio.fixture
async def be9663_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_product(tenant_key: str, session) -> str:
    product_id = str(uuid4())
    session.add(
        Product(
            id=product_id,
            name=f"BE9663 Product {uuid4().hex[:6]}",
            description="BE-9663 revive MCP boundary test",
            tenant_key=tenant_key,
            is_active=True,
            product_memory={},
        )
    )
    return product_id


def _project(project_id: str, tenant_key: str, product_id: str, *, name: str, status: str, **kwargs) -> Project:
    return Project(
        id=project_id,
        tenant_key=tenant_key,
        product_id=product_id,
        name=name,
        description="BE-9663 revive MCP boundary test project",
        mission=kwargs.pop("mission", "test mission"),
        status=status,
        series_number=kwargs.pop("series_number", random.randint(1, 9999)),
        **kwargs,
    )


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(AgentExecution).where(AgentExecution.tenant_key == tenant_key))
        await session.execute(delete(AgentJob).where(AgentJob.tenant_key == tenant_key))
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


class TestReviveDeletedProjectMcpBoundary:

    async def test_reviving_deleted_project_clears_deleted_at_and_lists_it(self, be9663_client, db_manager):
        client, tenant_key = be9663_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(tenant_key, session)
            session.add(
                _project(
                    project_id,
                    tenant_key,
                    product_id,
                    name="Trashed project",
                    status="deleted",
                    deleted_at=datetime.now(UTC),
                    series_number=1,
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("update_project", {"project_id": project_id, "status": "inactive"})
            assert not result.is_error, f"revival must succeed: {result.content!r}"
            payload = _payload(result)
            assert payload.get("status") == "inactive"

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                project = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
            assert project.deleted_at is None, "revive over MCP must clear deleted_at"
            assert project.status == "inactive"

            async with client() as mcp_session:
                list_result = await mcp_session.call_tool("list_projects", {"product_id": product_id})
            assert not list_result.is_error
            listed = _payload(list_result)
            listed_ids = {p.get("project_id") or p.get("id") for p in listed.get("projects", [])}
            assert project_id in listed_ids, "a revived project must be listed, not still hidden as trashed"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_reviving_deleted_project_does_not_let_a_new_project_reuse_its_serial(
        self, be9663_client, db_manager
    ):
        client, tenant_key = be9663_client
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product_id = await _seed_product(tenant_key, session)
            session.add(
                _project(
                    project_id,
                    tenant_key,
                    product_id,
                    name="Trashed project",
                    status="deleted",
                    deleted_at=datetime.now(UTC),
                    series_number=1,
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                revive_result = await mcp_session.call_tool(
                    "update_project", {"project_id": project_id, "status": "inactive"}
                )
            assert not revive_result.is_error

            async with client() as mcp_session:
                create_result = await mcp_session.call_tool(
                    "create_project",
                    {
                        "name": "Newcomer",
                        "mission": "m",
                        "description": "d",
                        "product_id": product_id,
                    },
                )
            assert not create_result.is_error, f"create must succeed: {create_result.content!r}"
            new_payload = _payload(create_result)

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                revived = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
                newcomer = (
                    await verify.execute(select(Project).where(Project.id == new_payload["project_id"]))
                ).scalar_one()

            assert newcomer.series_number != revived.series_number, (
                "a project revived over MCP must not have its serial reissued to a new project "
                f"(both are {newcomer.series_number})"
            )
        finally:
            await _cleanup(db_manager, tenant_key)
