# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.models.products import Product
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio




def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
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


def _assert_clean_membership_rejection(call_tool_result, product_id: str) -> None:
    text = _content_text(call_tool_result)
    assert "was not found for this account" in text, f"expected the membership-check rejection, got: {text!r}"
    assert product_id in text, f"the rejection must name the id it refused: {text!r}"
    assert "internal error" not in text.lower(), f"rejection was sanitized as a server error: {text!r}"


async def _seed_product(db_manager, tenant_key: str, *, label: str, is_active: bool) -> tuple[str, str]:
    product_id = str(uuid4())
    name = f"BE9499a {label} {uuid4().hex[:6]}"
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=name,
                description=f"BE-9499a boundary test product ({label})",
                tenant_key=tenant_key,
                is_active=is_active,
                product_memory={},
            )
        )
        await session.commit()
    return product_id, name


async def _seed_two_products(db_manager, tenant_key: str) -> tuple[tuple[str, str], tuple[str, str]]:
    active = await _seed_product(db_manager, tenant_key, label="active", is_active=True)
    other = await _seed_product(db_manager, tenant_key, label="intended", is_active=False)
    return active, other


async def _cleanup(db_manager, *tenant_keys: str) -> None:
    for tenant_key in tenant_keys:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await session.commit()




@pytest_asyncio.fixture
async def read_tools_client(db_manager, monkeypatch):
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




class TestExplicitProductIdWins:
    async def test_list_projects_with_explicit_product_id_ignores_the_active_product(
        self, read_tools_client, db_manager
    ):
        client, tenant_key = read_tools_client
        (active_id, _active_name), (intended_id, _intended_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_projects", {"product_id": intended_id})

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == intended_id, (
                f"listed {payload['product_id']!r}, expected the explicitly named "
                f"{intended_id!r} (active product was {active_id!r})"
            )
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_list_tasks_with_explicit_product_id_ignores_the_active_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        (active_id, _active_name), (intended_id, _intended_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_tasks", {"product_id": intended_id})

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == intended_id, (
                f"listed {payload['product_id']!r}, expected the explicitly named "
                f"{intended_id!r} (active product was {active_id!r})"
            )
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_get_roadmap_with_explicit_product_id_ignores_the_active_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        (active_id, _active_name), (intended_id, _intended_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("get_roadmap", {"product_id": intended_id})

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == intended_id, (
                f"read {payload['product_id']!r}, expected the explicitly named "
                f"{intended_id!r} (active product was {active_id!r})"
            )
        finally:
            await _cleanup(db_manager, tenant_key)




class TestOmittedProductIdFollowsActive:
    async def test_list_projects_without_product_id_uses_the_active_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_projects", {})

            assert result.is_error is False, _content_text(result)
            assert _payload(result)["product_id"] == active_id
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_list_tasks_without_product_id_uses_the_active_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_tasks", {})

            assert result.is_error is False, _content_text(result)
            assert _payload(result)["product_id"] == active_id
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_get_roadmap_without_product_id_uses_the_active_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("get_roadmap", {})

            assert result.is_error is False, _content_text(result)
            assert _payload(result)["product_id"] == active_id
        finally:
            await _cleanup(db_manager, tenant_key)




class TestInvalidProductIdIsRejected:
    async def test_list_projects_rejects_another_tenants_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_projects", {"product_id": foreign_id})

            assert result.is_error is True, f"a foreign product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, foreign_id)
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)

    async def test_list_tasks_rejects_another_tenants_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_tasks", {"product_id": foreign_id})

            assert result.is_error is True, f"a foreign product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, foreign_id)
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)

    async def test_get_roadmap_rejects_another_tenants_product(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("get_roadmap", {"product_id": foreign_id})

            assert result.is_error is True, f"a foreign product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, foreign_id)
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)

    async def test_list_projects_rejects_unknown_product_id(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        await _seed_two_products(db_manager, tenant_key)
        bogus_id = str(uuid4())

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_projects", {"product_id": bogus_id})

            assert result.is_error is True, f"an unknown product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, bogus_id)
        finally:
            await _cleanup(db_manager, tenant_key)




class TestResponseEchoesTheBinding:
    async def test_list_projects_echoes_product_id_on_the_default_path(self, read_tools_client, db_manager):
        client, tenant_key = read_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool("list_projects", {})

            assert result.is_error is False, _content_text(result)
            assert _payload(result)["product_id"] == active_id
        finally:
            await _cleanup(db_manager, tenant_key)
