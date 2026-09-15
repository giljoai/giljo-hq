# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.models.tasks import Task
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
    name = f"BE9411 {label} {uuid4().hex[:6]}"
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=name,
                description=f"BE-9411 boundary test product ({label})",
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


async def _set_active_product(db_manager, tenant_key: str, product_id: str) -> None:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        products = (await session.execute(select(Product).where(Product.tenant_key == tenant_key))).scalars().all()
        for product in products:
            product.is_active = False
        await session.flush()

        for product in products:
            if product.id == product_id:
                product.is_active = True
        await session.commit()


async def _task_product_id(db_manager, tenant_key: str, task_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        task = (await session.execute(select(Task).where(Task.id == task_id))).scalar_one()
        return task.product_id


async def _project_product_id(db_manager, tenant_key: str, project_id: str) -> str:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        project = (await session.execute(select(Project).where(Project.id == project_id))).scalar_one()
        return project.product_id


async def _count_rows_on_product(db_manager, tenant_key: str, product_id: str) -> tuple[int, int]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        tasks = (await session.execute(select(Task).where(Task.product_id == product_id))).scalars().all()
        projects = (await session.execute(select(Project).where(Project.product_id == product_id))).scalars().all()
        return len(tasks), len(projects)


async def _cleanup(db_manager, *tenant_keys: str) -> None:
    for tenant_key in tenant_keys:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            await session.execute(delete(Task).where(Task.tenant_key == tenant_key))
            await session.execute(delete(Project).where(Project.tenant_key == tenant_key))
            await session.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await session.execute(delete(Product).where(Product.tenant_key == tenant_key))
            await session.commit()




@pytest_asyncio.fixture
async def create_tools_client(db_manager, monkeypatch):
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
    async def test_create_task_with_explicit_product_id_ignores_the_active_product(
        self, create_tools_client, db_manager
    ):
        client, tenant_key = create_tools_client
        (active_id, _active_name), (intended_id, intended_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {
                        "title": "file against my own product",
                        "description": "explicit product_id must beat the active product",
                        "product_id": intended_id,
                    },
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == intended_id, (
                f"task bound to {payload['product_id']!r}, expected the explicitly named "
                f"{intended_id!r} (active product was {active_id!r})"
            )
            assert payload["product_name"] == intended_name
            assert await _task_product_id(db_manager, tenant_key, payload["task_id"]) == intended_id
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_with_explicit_product_id_ignores_the_active_product(
        self, create_tools_client, db_manager
    ):
        client, tenant_key = create_tools_client
        (active_id, _active_name), (intended_id, intended_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {
                        "name": "Explicitly bound project",
                        "description": "explicit product_id must beat the active product",
                        "product_id": intended_id,
                    },
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == intended_id, (
                f"project bound to {payload['product_id']!r}, expected the explicitly named "
                f"{intended_id!r} (active product was {active_id!r})"
            )
            assert payload["product_name"] == intended_name
            assert await _project_product_id(db_manager, tenant_key, payload["project_id"]) == intended_id
        finally:
            await _cleanup(db_manager, tenant_key)




class TestOmittedProductIdFollowsActive:

    async def test_create_task_without_product_id_uses_the_active_product(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        active_id, active_name = await _seed_product(db_manager, tenant_key, label="only", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "default binding", "description": "no product_id supplied"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
            assert await _task_product_id(db_manager, tenant_key, payload["task_id"]) == active_id
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_without_product_id_uses_the_active_product(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        active_id, active_name = await _seed_product(db_manager, tenant_key, label="only", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {"name": "Default bound project", "description": "no product_id supplied"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
            assert await _project_product_id(db_manager, tenant_key, payload["project_id"]) == active_id
        finally:
            await _cleanup(db_manager, tenant_key)




class TestActiveProductFlipRace:
    async def test_flip_between_two_creates_moves_the_default_and_not_the_explicit(
        self, create_tools_client, db_manager
    ):
        client, tenant_key = create_tools_client
        (first_active_id, _first_name), (second_id, _second_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                explicit = await mcp_session.call_tool(
                    "create_task",
                    {
                        "title": "pinned to the product I named",
                        "description": "created before the flip, naming the non-active product",
                        "product_id": second_id,
                    },
                )
                assert explicit.is_error is False, _content_text(explicit)

                await _set_active_product(db_manager, tenant_key, second_id)

                default = await mcp_session.call_tool(
                    "create_task",
                    {"title": "no longer carried by the flip", "description": "created after the flip, no product_id"},
                )
                assert default.is_error is False, _content_text(default)

            explicit_payload = _payload(explicit)
            default_payload = _payload(default)

            assert explicit_payload["product_id"] == second_id
            assert await _task_product_id(db_manager, tenant_key, explicit_payload["task_id"]) == second_id

            assert default_payload.get("success") is False
            assert default_payload.get("error") == "PRODUCT_AMBIGUOUS"
            first_tasks, _ = await _count_rows_on_product(db_manager, tenant_key, first_active_id)
            second_tasks, _ = await _count_rows_on_product(db_manager, tenant_key, second_id)
            assert second_tasks == 1, "only the earlier EXPLICIT create should have landed on second_id"
            assert first_tasks == 0, "a refused default create must not fall back to the (now-active) first product"
        finally:
            await _cleanup(db_manager, tenant_key)




class TestInvalidProductIdIsRejected:
    async def test_create_task_rejects_another_tenants_product(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "cross-tenant attempt", "description": "must be refused", "product_id": foreign_id},
                )

            assert result.is_error is True, f"a foreign product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, foreign_id)
            tasks_here, _ = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert tasks_here == 0, "a refused create must NOT silently fall back to the active product"
            foreign_tasks, _ = await _count_rows_on_product(db_manager, foreign_tenant_key, foreign_id)
            assert foreign_tasks == 0, "a refused create must not write into the other tenant either"
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)

    async def test_create_project_rejects_another_tenants_product(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {
                        "name": "Cross-tenant attempt",
                        "description": "must be refused",
                        "product_id": foreign_id,
                    },
                )

            assert result.is_error is True, f"a foreign product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, foreign_id)
            _, projects_here = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert projects_here == 0, "a refused create must NOT silently fall back to the active product"
            _, foreign_projects = await _count_rows_on_product(db_manager, foreign_tenant_key, foreign_id)
            assert foreign_projects == 0, "a refused create must not write into the other tenant either"
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)

    async def test_create_task_rejects_unknown_product_id(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        bogus_id = str(uuid4())
        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "bad id", "description": "must be refused", "product_id": bogus_id},
                )

            assert result.is_error is True, f"an unknown product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, bogus_id)
            tasks_here, _ = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert tasks_here == 0, "a refused create must NOT silently fall back to the active product"
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_rejects_unknown_product_id(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)

        bogus_id = str(uuid4())
        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {"name": "Bad id", "description": "must be refused", "product_id": bogus_id},
                )

            assert result.is_error is True, f"an unknown product_id must be refused, got: {_content_text(result)!r}"
            _assert_clean_membership_rejection(result, bogus_id)
            _, projects_here = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert projects_here == 0, "a refused create must NOT silently fall back to the active product"
        finally:
            await _cleanup(db_manager, tenant_key)


class TestPreExistingServicePathIsValidatedToo:

    async def test_create_project_for_mcp_refuses_a_foreign_product_id_directly(self, create_tools_client, db_manager):
        from giljo_mcp.exceptions import ValidationError
        from giljo_mcp.tools.tool_accessor import ToolAccessor

        _client, tenant_key = create_tools_client
        (active_id, _active_name), _other = await _seed_two_products(db_manager, tenant_key)
        foreign_tenant_key = TenantManager.generate_tenant_key()
        foreign_id, _foreign_name = await _seed_product(db_manager, foreign_tenant_key, label="foreign", is_active=True)

        tenant_manager = TenantManager()
        tenant_manager.set_current_tenant(tenant_key)
        accessor = ToolAccessor(db_manager=db_manager, tenant_manager=tenant_manager)

        try:
            with pytest.raises(ValidationError) as exc_info:
                await accessor._project_service.create_project_for_mcp(
                    name="Direct service-layer cross-tenant attempt",
                    description="must be refused below the MCP boundary too",
                    product_id=foreign_id,
                    tenant_key=tenant_key,
                )

            message = str(exc_info.value)
            assert "was not found for this account" in message, message
            assert foreign_id in message, message

            _, projects_here = await _count_rows_on_product(db_manager, tenant_key, active_id)
            assert projects_here == 0, "the refused service-layer create must not fall back to the active product"
            _, foreign_projects = await _count_rows_on_product(db_manager, foreign_tenant_key, foreign_id)
            assert foreign_projects == 0, "the refused service-layer create must not write into the other tenant"
        finally:
            await _cleanup(db_manager, tenant_key, foreign_tenant_key)




class TestResponseEchoesTheBinding:

    async def test_create_task_echoes_product_id_and_name_on_the_default_path(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        active_id, active_name = await _seed_product(db_manager, tenant_key, label="only", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "echo check", "description": "response must name the product"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_echoes_product_id_and_name_on_the_default_path(self, create_tools_client, db_manager):
        client, tenant_key = create_tools_client
        active_id, active_name = await _seed_product(db_manager, tenant_key, label="only", is_active=True)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {"name": "Echo check", "description": "response must name the product"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["product_id"] == active_id
            assert payload["product_name"] == active_name
        finally:
            await _cleanup(db_manager, tenant_key)




class TestBareCreateIsRejectedWhenAmbiguous:

    async def test_create_task_without_product_id_is_rejected_on_a_multi_product_tenant(
        self, create_tools_client, db_manager
    ):
        client, tenant_key = create_tools_client
        (active_id, active_name), (other_id, other_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_task",
                    {"title": "ambiguous binding", "description": "no product_id supplied, two products exist"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["success"] is False
            assert payload["error"] == "PRODUCT_AMBIGUOUS"
            product_ids = {p["id"] for p in payload["products"]}
            assert product_ids == {active_id, other_id}
            by_id = {p["id"]: p for p in payload["products"]}
            assert by_id[active_id]["name"] == active_name
            assert by_id[active_id]["is_active"] is True
            assert by_id[other_id]["name"] == other_name
            assert by_id[other_id]["is_active"] is False

            active_tasks, _ = await _count_rows_on_product(db_manager, tenant_key, active_id)
            other_tasks, _ = await _count_rows_on_product(db_manager, tenant_key, other_id)
            assert active_tasks == 0, "a refused create must NOT silently fall back to the active product"
            assert other_tasks == 0
        finally:
            await _cleanup(db_manager, tenant_key)

    async def test_create_project_without_product_id_is_rejected_on_a_multi_product_tenant(
        self, create_tools_client, db_manager
    ):
        client, tenant_key = create_tools_client
        (active_id, active_name), (other_id, other_name) = await _seed_two_products(db_manager, tenant_key)

        try:
            async with client() as mcp_session:
                result = await mcp_session.call_tool(
                    "create_project",
                    {"name": "Ambiguous project", "description": "no product_id supplied, two products exist"},
                )

            assert result.is_error is False, _content_text(result)
            payload = _payload(result)
            assert payload["success"] is False
            assert payload["error"] == "PRODUCT_AMBIGUOUS"
            product_ids = {p["id"] for p in payload["products"]}
            assert product_ids == {active_id, other_id}
            by_id = {p["id"]: p for p in payload["products"]}
            assert by_id[active_id]["name"] == active_name
            assert by_id[active_id]["is_active"] is True
            assert by_id[other_id]["name"] == other_name
            assert by_id[other_id]["is_active"] is False

            _, active_projects = await _count_rows_on_product(db_manager, tenant_key, active_id)
            _, other_projects = await _count_rows_on_product(db_manager, tenant_key, other_id)
            assert active_projects == 0, "a refused create must NOT silently fall back to the active product"
            assert other_projects == 0
        finally:
            await _cleanup(db_manager, tenant_key)
