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
async def non_active_product_client(db_manager, monkeypatch):
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


async def _seed_two_products_one_active(db_manager, tenant_key: str) -> tuple[str, str, str]:
    active_product_id = str(uuid4())
    other_product_id = str(uuid4())
    project_id = str(uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=active_product_id,
                name=f"BE9435 Active {uuid4().hex[:6]}",
                description="the product that happens to be active",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            Product(
                id=other_product_id,
                name=f"BE9435 Other {uuid4().hex[:6]}",
                description="the product the edited project actually belongs to",
                tenant_key=tenant_key,
                is_active=False,
                product_memory={},
            )
        )
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=other_product_id,
                name="Original name",
                description="owned by the product that is not currently selected",
                mission="be edited without a product flip",
                status="inactive",
                staging_status="staging_complete",
                series_number=random.randint(1, 9999),
            )
        )
        await session.commit()

    return active_product_id, other_product_id, project_id


async def _cleanup(db_manager, tenant_key: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
        await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
        await session.commit()


class TestUpdateProjectNonActiveProductBoundary:
    async def test_updating_a_project_in_a_non_active_product_succeeds(self, non_active_product_client, db_manager):
        client, tenant_key = non_active_product_client
        _active_product_id, other_product_id, project_id = await _seed_two_products_one_active(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project",
                    {"project_id": project_id, "name": "Renamed without flipping products"},
                )

            assert not result.is_error, (
                f"updating a project in a non-active product must not error. content: {_content_text(result)!r}"
            )

            payload = _payload(result)
            assert payload.get("success") is True, f"Expected success==True, got: {payload!r}"

            wire_text = _content_text(result)
            assert "Activate the project's own product" not in wire_text, wire_text
            assert "but the active product is" not in wire_text, wire_text

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                stored = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
            assert stored.name == "Renamed without flipping products"
            assert stored.product_id == other_product_id, "the edit must not have moved the project's product"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_updating_a_project_with_no_active_product_at_all_succeeds(
        self, non_active_product_client, db_manager
    ):
        client, tenant_key = non_active_product_client
        product_id = str(uuid4())
        project_id = str(uuid4())

        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            session.add(
                Product(
                    id=product_id,
                    name=f"BE9435 Deselected {uuid4().hex[:6]}",
                    description="a product nobody has selected",
                    tenant_key=tenant_key,
                    is_active=False,
                    product_memory={},
                )
            )
            session.add(
                Project(
                    id=project_id,
                    tenant_key=tenant_key,
                    product_id=product_id,
                    name="Original name",
                    description="owned by a tenant with nothing selected",
                    mission="be edited with no product active",
                    status="inactive",
                    staging_status="staging_complete",
                    series_number=random.randint(1, 9999),
                )
            )
            await session.commit()

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project",
                    {"project_id": project_id, "name": "Renamed with nothing selected"},
                )

            assert not result.is_error, f"no active product must not block an edit. content: {_content_text(result)!r}"
            assert _payload(result).get("success") is True, _content_text(result)
            assert "No active product set" not in _content_text(result), _content_text(result)

            async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
                stored = (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()
            assert stored.name == "Renamed with nothing selected"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_another_tenants_project_is_still_reported_as_nonexistent(
        self, non_active_product_client, db_manager
    ):
        client, tenant_key = non_active_product_client
        foreign_tenant_key = TenantManager.generate_tenant_key()
        _active, _other, foreign_project_id = await _seed_two_products_one_active(db_manager, foreign_tenant_key)
        await _seed_two_products_one_active(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "update_project",
                    {"project_id": foreign_project_id, "name": "should never land"},
                )

            wire_text = _content_text(result)
            lowered = wire_text.lower()
            assert "not found" in lowered or "does not exist" in lowered, (
                f"a foreign-tenant project must read as nonexistent. content: {wire_text!r}"
            )

            async with db_manager.get_session_async(tenant_key=foreign_tenant_key) as verify:
                stored = (await verify.execute(select(Project).where(Project.id == foreign_project_id))).scalar_one()
            assert stored.name == "Original name", "a cross-tenant write must not have landed"
        finally:
            await _cleanup(db_manager, tenant_key)
            await _cleanup(db_manager, foreign_tenant_key)
