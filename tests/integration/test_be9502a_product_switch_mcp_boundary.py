# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9502a — product activate/deactivate/switch reachable from the harness, tested
AT the MCP transport boundary (CLAUDE.md's BE-5042 rule: test at the layer that
failed before, and a boundary change needs a boundary test).

``update_product_context`` (the existing tool — no new tool, per the roster lock)
grows an optional ``is_active`` param that routes through
``ProductService.activate_product`` / ``deactivate_product`` -- the SAME owning
writer ``POST /api/products/{id}/activate|deactivate`` uses (dual-door,
single-writer). Deliberately NOT the generic field merge-write: that path
would bypass the one owning writer for this field, same as any other
service-owned column. (FE-9524/D1: the sibling auto-deactivate this docstring
used to describe is retired -- several products may be shown at once.)

Mirrors the fixtures in test_fe9320_update_product_context_boundary.py (Section B:
real ToolAccessor on the rolled-back test session).
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models import Product
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


def _error_text(result) -> str:
    return "\n".join(block.text for block in (result.content or []) if getattr(block, "text", None))


@pytest_asyncio.fixture
async def product_switch_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools import vision_analysis
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    real_update = vision_analysis.update_product_fields

    async def _update_on_test_session(*args, **kwargs):
        kwargs.setdefault("_test_session", db_session)
        return await real_update(*args, **kwargs)

    monkeypatch.setattr(vision_analysis, "update_product_fields", _update_on_test_session)

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_two_products(session, tenant_key: str) -> tuple[Product, Product]:
    active = Product(id=str(uuid.uuid4()), name="BE-9502a active", tenant_key=tenant_key, is_active=True)
    inactive = Product(id=str(uuid.uuid4()), name="BE-9502a inactive", tenant_key=tenant_key, is_active=False)
    session.add(active)
    session.add(inactive)
    await session.flush()
    return active, inactive


@pytest.mark.asyncio
async def test_switching_products_leaves_the_sibling_shown(product_switch_client):
    """FE-9524/D1: showing product B while A is shown must leave A shown too --
    several tabs open is the point, and the single-active-per-tenant invariant
    this test used to pin is exactly what D1 retires (DB index dropped in
    ce_0099, service-layer sibling-deactivate removed from activate_product)."""
    new_client, tenant_key, session = product_switch_client
    active, inactive = await _seed_two_products(session, tenant_key)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "update_product_context",
            {"product_id": inactive.id, "is_active": True},
        )
    assert result.is_error is False, _error_text(result)
    assert result.structured_content["is_active"] is True

    rows = (await session.execute(select(Product).where(Product.tenant_key == tenant_key))).scalars().all()
    by_id = {p.id: p for p in rows}
    assert by_id[inactive.id].is_active is True
    assert by_id[active.id].is_active is True


@pytest.mark.asyncio
async def test_deactivating_the_active_product_leaves_none_active(product_switch_client):
    new_client, tenant_key, session = product_switch_client
    active, _inactive = await _seed_two_products(session, tenant_key)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "update_product_context",
            {"product_id": active.id, "is_active": False},
        )
    assert result.is_error is False, _error_text(result)
    assert result.structured_content["is_active"] is False

    await session.refresh(active)
    assert active.is_active is False


@pytest.mark.asyncio
async def test_is_active_omitted_leaves_activation_state_untouched(product_switch_client):
    """Byte-identical for existing callers: a plain field-only update_product_context
    call must not move activation state at all."""
    new_client, tenant_key, session = product_switch_client
    active, inactive = await _seed_two_products(session, tenant_key)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "update_product_context",
            {"product_id": active.id, "product_name": "Renamed while active"},
        )
    assert result.is_error is False, _error_text(result)
    assert "is_active" not in result.structured_content

    await session.refresh(active)
    await session.refresh(inactive)
    assert active.is_active is True
    assert inactive.is_active is False


@pytest.mark.asyncio
async def test_activating_an_unknown_product_id_is_a_clean_rejection_not_a_500(product_switch_client):
    new_client, tenant_key, session = product_switch_client
    await _seed_two_products(session, tenant_key)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "update_product_context",
            {"product_id": str(uuid.uuid4()), "is_active": True},
        )
    assert result.is_error is True
    assert "not found" in _error_text(result).lower()


@pytest.mark.asyncio
async def test_switch_and_field_correction_land_in_the_same_call(product_switch_client):
    """Combines both DoD asks (switch + post-creation field correction) in one call."""
    new_client, tenant_key, session = product_switch_client
    _active, inactive = await _seed_two_products(session, tenant_key)

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "update_product_context",
            {
                "product_id": inactive.id,
                "is_active": True,
                "tech_stack": {"target_platforms": ["web", "linux"]},
            },
        )
    assert result.is_error is False, _error_text(result)
    assert result.structured_content["is_active"] is True

    await session.refresh(inactive)
    assert inactive.is_active is True
    assert inactive.target_platforms == ["web", "linux"]
