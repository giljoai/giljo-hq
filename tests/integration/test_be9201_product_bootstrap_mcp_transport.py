# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Transport-layer regression tests for the BE-9201 product-bootstrap MCP tools.

The BE-5042 lesson: a tool can pass every service-layer test yet fail at the
FastMCP ``@mcp.tool`` wrapper (never register, mangle kwargs, drop tenant_key).
These tests drive ``create_product`` and ``create_vision_document`` THROUGH the
in-memory MCP transport — the exact layer the tools were added at.

What this file does NOT do: re-test ProductService / ProductVisionService
internals (duplicate-name rejection shapes, chunking mechanics, consolidation
hashing). Function-layer coverage lives in
``tests/services/test_be9201_product_bootstrap.py``.

Pattern reference: ``tests/integration/test_task_tools_mcp_transport.py`` —
same in-memory ``create_connected_server_and_client_session`` transport, same
``_resolve_tenant`` monkeypatch (the in-memory transport has no HTTP scope /
auth middleware). Delta: the ToolAccessor is constructed with
``test_session=db_session`` so the BE-9201 adapters (which build
ProductService / ProductVisionService per call honoring ``self._test_session``)
share the test's transactional session.
"""

from __future__ import annotations

import json
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import Product, VisionDocument
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    """Decode a CallToolResult into a dict (mirrors the harness helper)."""
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    """Concatenate error text blocks from an error CallToolResult."""
    parts = []
    for block in call_tool_result.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


@pytest_asyncio.fixture
async def primary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def secondary_tenant_key() -> str:
    return TenantManager.generate_tenant_key()


class _TenantSwitch:
    """Mutable holder so tests can flip the resolved tenant_key per call."""

    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def bootstrap_mcp_client(db_manager, db_session, primary_tenant_key, monkeypatch):
    """Yield ``(new_client, tenant_switch)`` against the live FastMCP server.

    The accessor carries ``test_session=db_session`` so the BE-9201 adapters'
    per-call ProductService / ProductVisionService constructions join the
    test's transaction (writes visible to the test's own queries, rolled back
    at teardown).
    """
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

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        test_session=db_session,
    )
    state.tool_accessor = accessor

    tenant_switch = _TenantSwitch(primary_tenant_key)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_switch.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_switch
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


# ---------------------------------------------------------------------------
# create_product wrapper
# ---------------------------------------------------------------------------


async def test_create_product_happy_path(bootstrap_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = bootstrap_mcp_client
    name = f"Bootstrap Product {uuid4().hex[:8]}"

    async with new_client() as session:
        result = await session.call_tool(
            "create_product",
            {"name": name, "description": "created by the onboarding agent"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["product_id"]
    assert payload["name"] == name
    # FE-9524/D1: a bootstrapped product is shown by default -- no on/off
    # ceremony left for the user to perform.
    assert payload["is_active"] is True
    assert payload["target_platforms"] == ["all"]

    # The row landed tenant-scoped. (tenant_session_context authorizes this
    # test's own tenant-predicated select against the guard.)
    with tenant_session_context(db_session, primary_tenant_key):
        row = (
            await db_session.execute(
                select(Product).where(Product.id == payload["product_id"], Product.tenant_key == primary_tenant_key)
            )
        ).scalar_one_or_none()
    assert row is not None
    assert row.description == "created by the onboarding agent"


async def test_create_product_optional_fields_and_platforms(bootstrap_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = bootstrap_mcp_client
    name = f"Full Product {uuid4().hex[:8]}"

    async with new_client() as session:
        result = await session.call_tool(
            "create_product",
            {
                "name": name,
                "project_path": "C:/repos/my-app",
                "core_features": "auth, billing",
                "brand_guidelines": "dark theme",
                "target_platforms": ["web", "windows"],
            },
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["project_path"] == "C:/repos/my-app"
    assert payload["target_platforms"] == ["web", "windows"]


async def test_create_product_duplicate_name_is_actionable_error(bootstrap_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = bootstrap_mcp_client
    name = f"Dup Product {uuid4().hex[:8]}"

    async with new_client() as session:
        first = await session.call_tool("create_product", {"name": name})
    assert first.is_error is False, _error_text(first)

    async with new_client() as session:
        second = await session.call_tool("create_product", {"name": name})
    assert second.is_error is True
    assert "already exists" in _error_text(second)


async def test_create_product_invalid_platform_is_actionable_error(bootstrap_mcp_client):
    new_client, _switch = bootstrap_mcp_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_product",
            {"name": f"Bad Platforms {uuid4().hex[:8]}", "target_platforms": ["web", "vax"]},
        )

    assert result.is_error is True
    assert "Invalid platform values" in _error_text(result)


async def test_create_product_whitespace_name_rejected(bootstrap_mcp_client):
    """min_length=1 catches '' at the FastMCP boundary; the adapter catches '  '."""
    new_client, _switch = bootstrap_mcp_client

    async with new_client() as session:
        result = await session.call_tool("create_product", {"name": "   "})

    assert result.is_error is True
    assert "name" in _error_text(result).lower()


# ---------------------------------------------------------------------------
# create_vision_document wrapper
# ---------------------------------------------------------------------------


async def _create_product_via_tool(new_client) -> str:
    async with new_client() as session:
        result = await session.call_tool("create_product", {"name": f"Vision Host {uuid4().hex[:8]}"})
    assert result.is_error is False, _error_text(result)
    return _payload(result)["product_id"]


async def test_create_vision_document_happy_path(bootstrap_mcp_client, db_session, primary_tenant_key):
    new_client, _switch = bootstrap_mcp_client
    product_id = await _create_product_via_tool(new_client)

    content = "# Vision\n\nAn onboarding-agent-authored product vision.\n\n## Goals\n\nShip the tutorial."
    async with new_client() as session:
        result = await session.call_tool(
            "create_vision_document",
            {"product_id": product_id, "content": content, "document_name": "Product Vision.md"},
        )

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is True
    assert payload["document_id"]
    assert payload["document_name"] == "Product Vision.md"

    # The doc landed through the SAME ingest path the REST upload uses:
    # inline storage, active, tenant-scoped.
    with tenant_session_context(db_session, primary_tenant_key):
        doc = (
            await db_session.execute(
                select(VisionDocument).where(
                    VisionDocument.id == payload["document_id"],
                    VisionDocument.tenant_key == primary_tenant_key,
                )
            )
        ).scalar_one_or_none()
        assert doc is not None
        assert doc.product_id == product_id
        assert doc.storage_type == "inline"
        assert doc.is_active is True
        assert doc.vision_document == content

        # BE-5118 parity with the REST upload: a fresh unsummarized doc keeps
        # the completion flag FALSE until the agent writes summaries.
        product = (await db_session.execute(select(Product).where(Product.id == product_id))).scalar_one()
        assert product.vision_analysis_complete is False


async def test_create_vision_document_default_name_and_md_append(bootstrap_mcp_client, db_session):
    new_client, _switch = bootstrap_mcp_client
    product_id = await _create_product_via_tool(new_client)

    # Omitted name -> the agent default.
    async with new_client() as session:
        result = await session.call_tool(
            "create_vision_document",
            {"product_id": product_id, "content": "# Vision\n\nBody one."},
        )
    assert result.is_error is False, _error_text(result)
    assert _payload(result)["document_name"] == "Agent Vision.md"

    # Extensionless name -> .md appended (UI upload allowlist parity).
    async with new_client() as session:
        result2 = await session.call_tool(
            "create_vision_document",
            {"product_id": product_id, "content": "# Vision\n\nBody two.", "document_name": "roadmap"},
        )
    assert result2.is_error is False, _error_text(result2)
    assert _payload(result2)["document_name"] == "roadmap.md"


async def test_create_vision_document_blank_content_rejected(bootstrap_mcp_client):
    """min_length=1 catches '' at the boundary; the tool-function catches '  '."""
    new_client, _switch = bootstrap_mcp_client
    product_id = await _create_product_via_tool(new_client)

    async with new_client() as session:
        result = await session.call_tool(
            "create_vision_document",
            {"product_id": product_id, "content": "   "},
        )

    assert result.is_error is True
    assert "content" in _error_text(result).lower()


async def test_create_vision_document_unknown_product_not_found(bootstrap_mcp_client):
    new_client, _switch = bootstrap_mcp_client

    async with new_client() as session:
        result = await session.call_tool(
            "create_vision_document",
            {"product_id": str(uuid4()), "content": "# Vision\n\nOrphan."},
        )

    assert result.is_error is True
    assert "not found" in _error_text(result).lower()


# ---------------------------------------------------------------------------
# Tenant isolation through the transport
# ---------------------------------------------------------------------------


async def test_create_vision_document_is_tenant_scoped(
    bootstrap_mcp_client, db_session, primary_tenant_key, secondary_tenant_key
):
    """Tenant B must NOT be able to attach a vision doc to tenant A's product."""
    new_client, switch = bootstrap_mcp_client

    switch.value = primary_tenant_key
    product_id = await _create_product_via_tool(new_client)

    switch.value = secondary_tenant_key
    async with new_client() as session:
        result = await session.call_tool(
            "create_vision_document",
            {"product_id": product_id, "content": "# Cross-tenant\n\nMust not land."},
        )

    assert result.is_error is True
    assert "not found" in _error_text(result).lower(), (
        "TENANT LEAK: tenant B attached a vision document to tenant A's product."
    )

    # And no doc row exists for that product (checked as the owning tenant).
    with tenant_session_context(db_session, primary_tenant_key):
        docs = (
            (await db_session.execute(select(VisionDocument).where(VisionDocument.product_id == product_id)))
            .scalars()
            .all()
        )
    assert docs == []


async def test_create_product_names_are_per_tenant(bootstrap_mcp_client, primary_tenant_key, secondary_tenant_key):
    """The duplicate-name guard is tenant-scoped: B may reuse A's product name."""
    new_client, switch = bootstrap_mcp_client
    name = f"Shared Name {uuid4().hex[:8]}"

    switch.value = primary_tenant_key
    async with new_client() as session:
        a = await session.call_tool("create_product", {"name": name})
    assert a.is_error is False, _error_text(a)

    switch.value = secondary_tenant_key
    async with new_client() as session:
        b = await session.call_tool("create_product", {"name": name})
    assert b.is_error is False, _error_text(b)
    assert _payload(a)["product_id"] != _payload(b)["product_id"]
