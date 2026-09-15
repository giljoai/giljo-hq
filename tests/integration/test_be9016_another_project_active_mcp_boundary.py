# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

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


def _content_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def another_project_active_client(db_manager, monkeypatch):
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


async def _seed_active_product_with_two_projects(db_manager, tenant_key: str) -> tuple[str, str, str]:
    product_id = str(uuid4())
    active_project_id = str(uuid4())
    inactive_project_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE9016 Product {uuid4().hex[:6]}",
                description="BE-9016 another-project-active boundary test",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            Project(
                id=active_project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name="Already active",
                description="pre-existing active project",
                mission="stay active",
                status="active",
                staging_status="staging_complete",
                series_number=random.randint(1, 9000),
            )
        )
        session.add(
            Project(
                id=inactive_project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name="Second project",
                description="the one we try to activate",
                mission="try to become active too",
                status="parked",
                staging_status="staging_complete",
                series_number=random.randint(9001, 9999),
            )
        )
        await session.commit()

    return product_id, active_project_id, inactive_project_id


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


class TestAnotherProjectActiveMcpBoundary:
    async def test_activating_second_project_succeeds_both_active(self, another_project_active_client, db_manager):
        client, tenant_key = another_project_active_client
        _product_id, active_project_id, inactive_project_id = await _seed_active_product_with_two_projects(
            db_manager, tenant_key
        )

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project",
                    {"project_id": inactive_project_id, "status": "active"},
                )

            assert not result.is_error, f"expected a clean success, got: {_content_text(result)!r}"
            payload = _payload(result)
            assert payload.get("success", True) is not False, f"expected success, got: {payload!r}"

            wire_text = _content_text(result)
            assert "idx_project_single_active_per_product" not in wire_text
            assert "IntegrityError" not in wire_text

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                active = (await verify.execute(select(Project).where(Project.id == active_project_id))).scalar_one()
                second = (await verify.execute(select(Project).where(Project.id == inactive_project_id))).scalar_one()
            assert active.status == "active", "the pre-existing active project must be untouched"
            assert second.status == "active", "ruling 5 amended: the second activation must persist ACTIVE too"
        finally:
            await _cleanup(db_manager, tenant_key)
