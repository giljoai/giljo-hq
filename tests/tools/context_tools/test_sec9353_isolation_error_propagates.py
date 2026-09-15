# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import sys
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio

from giljo_mcp.models.product_agent_assignment import ProductAgentAssignment
from giljo_mcp.models.products import Product
from giljo_mcp.models.templates import AgentTemplate
from giljo_mcp.repositories.product_agent_assignment_repository import (
    ProductAgentAssignmentRepository,
)
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tenant_guard import TenantIsolationError
from giljo_mcp.tools.context_tools.fetch_context import fetch_context
from giljo_mcp.tools.context_tools.get_agent_templates import get_agent_templates


fetch_context_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]


pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def product(db_session, tenant_key):
    row = Product(
        id=str(uuid4()),
        name=f"Isolation Propagation Product {uuid4().hex[:6]}",
        description="agent-template isolation-propagation fixture",
        tenant_key=tenant_key,
        is_active=True,
        created_at=datetime.now(UTC),
    )
    db_session.add(row)
    await db_session.commit()
    return row


@pytest_asyncio.fixture
async def assigned_roster(db_session, tenant_key, product):
    templates = []
    for name in ("implementer", "tester", "reviewer"):
        row = AgentTemplate(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"{name}_{uuid4().hex[:6]}",
            role=name.title(),
            description=f"{name} description",
            is_active=True,
        )
        db_session.add(row)
        templates.append(row)
    db_session.add(
        ProductAgentAssignment(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            template_id=templates[0].id,
            is_active=True,
        )
    )
    await db_session.commit()
    return templates


async def _names(db_session, tenant_key, product) -> set[str]:
    result = await get_agent_templates(
        product_id=product.id,
        tenant_key=tenant_key,
        detail="basic",
        _test_session=db_session,
    )
    return {entry["name"] for entry in result["data"]}


def _raise_inside_guarded_block(monkeypatch, exc: Exception) -> None:

    async def _boom(self, session, product_id, tenant_key):
        raise exc

    monkeypatch.setattr(
        ProductAgentAssignmentRepository,
        "get_active_template_ids_for_product",
        _boom,
    )


async def test_tenant_isolation_error_propagates_out_of_the_tool(
    db_session, tenant_key, product, assigned_roster, monkeypatch
):
    _raise_inside_guarded_block(monkeypatch, TenantIsolationError("Tenant context required for ORM statement"))

    with pytest.raises(TenantIsolationError):
        await _names(db_session, tenant_key, product)


async def test_ordinary_runtime_error_still_falls_back_to_all_templates(
    db_session, tenant_key, product, assigned_roster, monkeypatch
):
    assert await _names(db_session, tenant_key, product) == {assigned_roster[0].name}, (
        "control failed: the assignment filter did not narrow the roster, so the "
        "fallback assertion below would prove nothing"
    )

    _raise_inside_guarded_block(monkeypatch, RuntimeError("transient connection reset"))

    assert await _names(db_session, tenant_key, product) == {t.name for t in assigned_roster}, (
        "an ordinary RuntimeError no longer falls back to showing all templates -- "
        "narrowing the catch changed behaviour for the transient case it was written for"
    )



_FETCH_PRODUCT_ID = "11111111-1111-1111-1111-111111111111"
_FETCH_TENANT_KEY = "tk_sec9353"
_FETCH_CATEGORIES = ["memory_360", "agent_templates", "vision_documents"]


def _patched_loop(raiser):

    async def fake_fetch(category: str, **_kwargs):
        if category == "agent_templates":
            raise raiser
        return {"source": category, "data": {"ok": category}, "metadata": {}}

    return (
        patch.object(fetch_context_module, "_fetch_category", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(fetch_context_module, "_load_user_depth_config", new=AsyncMock(return_value={})),
        patch.object(fetch_context_module, "_build_last_modified_map", new=AsyncMock(return_value={})),
    )


async def test_tenant_isolation_error_escapes_fetch_context():
    guard_error = TenantIsolationError("Tenant isolation bypass does not cover: ProductAgentAssignment")
    a, b, c, d = _patched_loop(guard_error)

    with a, b, c, d, pytest.raises(TenantIsolationError):
        await fetch_context(
            product_id=_FETCH_PRODUCT_ID,
            tenant_key=_FETCH_TENANT_KEY,
            categories=_FETCH_CATEGORIES,
            db_manager=object(),
        )


async def test_ordinary_category_error_still_reported_and_other_categories_survive():
    a, b, c, d = _patched_loop(RuntimeError("transient connection reset"))

    with a, b, c, d:
        response = await fetch_context(
            product_id=_FETCH_PRODUCT_ID,
            tenant_key=_FETCH_TENANT_KEY,
            categories=_FETCH_CATEGORIES,
            db_manager=object(),
        )

    assert [e["category"] for e in response.get("errors", [])] == ["agent_templates"], (
        "an ordinary per-category error is no longer reported in the errors block -- "
        f"per-category isolation was broken by the narrowing. got={response.get('errors')}"
    )
    assert "agent_templates" not in response["categories_returned"]
    assert response["data"]["memory_360"] == {"ok": "memory_360"}
    assert response["data"]["vision_documents"] == {"ok": "vision_documents"}
