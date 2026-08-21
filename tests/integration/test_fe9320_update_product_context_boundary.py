# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""FE-9320 — the update_product_context / get_vision_doc changes tested AT the MCP
boundary, through the real transport.

Two of FE-9320's changes live in the ``@mcp.tool`` wrapper, not the service:
``dev_tools`` as a tech_stack sub-key, and ``emit_completion`` as a parameter on the
EXISTING tool (no new tool — a new tool would add surface to a product about to be
submitted to a connector directory). CLAUDE.md's BE-5042 rule mandates a boundary
test for a boundary change: FastMCP silently DROPS an unknown top-level arg, so a
param that exists in the service but not on the wrapper loses data with a 200.

Section A drives the autospec transport (arg validation, no DB); Section B drives a
real ToolAccessor on the rolled-back ``db_session``. Both mirror the fixtures in
test_be9118_update_product_context_regroup.py.

Parallel-safe: fresh tenant key per test, rolled-back session, no module state.
"""

from __future__ import annotations

import inspect
import uuid

import pytest
import pytest_asyncio
from sqlalchemy import select

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.models import Product, VisionDocument
from giljo_mcp.models.products import ProductTechStack
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


def _error_text(result) -> str:
    return "\n".join(block.text for block in (result.content or []) if getattr(block, "text", None))


def _live_tool(name: str):
    for tool in mcp._tool_manager.list_tools():
        if tool.name == name:
            return tool
    raise AssertionError(f"{name} not registered on the live FastMCP surface")


# ---------------------------------------------------------------------------
# Section A — autospec transport: the params exist and validate.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    from unittest.mock import create_autospec

    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor
    from tests.helpers.mcp_dispatch import attach_registry_service_autospecs

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    accessor = create_autospec(ToolAccessor, instance=True)
    for attr_name in dir(ToolAccessor):
        if attr_name.startswith("_"):
            continue
        if inspect.iscoroutinefunction(getattr(ToolAccessor, attr_name, None)):
            getattr(accessor, attr_name).return_value = {"ok": True}
    attach_registry_service_autospecs(accessor, {"ok": True})

    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    state.db_manager = None

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


def test_emit_completion_is_a_param_on_the_existing_tool_not_a_new_tool():
    """The completion signal had to be a PARAMETER: a new MCP tool fires the
    app-surface/tool-count locks and adds surface to the connector listing."""
    params = _live_tool("update_product_context").parameters.get("properties", {})
    assert "emit_completion" in params, "emit_completion must be on the live tool schema"

    tool_names = {tool.name for tool in mcp._tool_manager.list_tools()}
    for forbidden in ("complete_vision_analysis", "finish_vision_analysis", "emit_vision_completion"):
        assert forbidden not in tool_names, f"FE-9320 must not add a tool ({forbidden})"


def test_dev_tools_is_reachable_as_a_tech_stack_subkey():
    """dev_tools is a real column; it must be addressable from the tool schema, or
    content about tooling again has nowhere to land."""
    tech_stack_schema = _live_tool("update_product_context").parameters["$defs"]["_TechStackContext"]
    assert "dev_tools" in tech_stack_schema["properties"]


@pytest.mark.asyncio
async def test_dev_tools_and_emit_completion_dispatch(autospec_mcp):
    """Positive: both new inputs pass FastMCP arg validation and dispatch."""
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "update_product_context",
            {
                "product_id": str(uuid.uuid4()),
                "tech_stack": {"programming_languages": "Python", "dev_tools": "ruff, pytest"},
                "emit_completion": True,
            },
        )
    assert result.is_error is False, f"must dispatch: {_error_text(result)}"


# ---------------------------------------------------------------------------
# Section B — DB-backed transport: staged calls through the real tool.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def product_context_client(db_manager, db_session, monkeypatch):
    """Real ToolAccessor on the transport with update_product_fields threaded onto
    the rolled-back test session (the accessor mixin imports the symbol at call
    time, so a module-level monkeypatch is what reaches it)."""
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


async def _seed(session, tenant_key: str) -> tuple[Product, VisionDocument]:
    product = Product(
        id=str(uuid.uuid4()),
        name="FE-9320 boundary",
        description="staged ingest",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    session.add(product)
    await session.flush()
    doc = VisionDocument(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        document_name="Vision.md",
        document_type="vision",
        vision_document="Vision content for the FE-9320 boundary test.",
        storage_type="inline",
        content_hash="fe9320boundary",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    session.add(doc)
    await session.flush()
    return product, doc


@pytest.mark.asyncio
async def test_staged_calls_complete_a_multi_part_ingest(product_context_client):
    """DoD 4 + 5, at the boundary: THREE staged calls finish the analysis, and each
    response reports the completion state instead of leaving the agent to infer it.
    The one-call mandate is what died at 62,420 bytes on a real run."""
    new_client, tenant_key, session = product_context_client
    product, doc = await _seed(session, tenant_key)

    async with new_client() as mcp_session:
        first = await mcp_session.call_tool(
            "update_product_context",
            {
                "product_id": product.id,
                "tech_stack": {"programming_languages": "Python", "dev_tools": "ruff, pytest, Vite"},
            },
        )
        assert first.is_error is False, _error_text(first)
        assert first.structured_content["vision_analysis_complete"] is False
        assert first.structured_content["missing_for_completion"]

        second = await mcp_session.call_tool(
            "update_product_context",
            {
                "product_id": product.id,
                "vision_summaries": [{"doc_id": doc.id, "light": "Light.", "medium": "Medium."}],
            },
        )
        assert second.is_error is False, _error_text(second)
        assert second.structured_content["vision_analysis_complete"] is False

        third = await mcp_session.call_tool(
            "update_product_context",
            {
                "product_id": product.id,
                "consolidated_vision": {"light": "Consolidated light.", "medium": "Consolidated medium."},
                "emit_completion": True,
            },
        )
        assert third.is_error is False, _error_text(third)
        assert third.structured_content["vision_analysis_complete"] is True
        assert third.structured_content["missing_for_completion"] == []

    # dev_tools actually reached its column through the transport...
    ts = (
        await session.execute(
            select(ProductTechStack).where(
                ProductTechStack.product_id == product.id,
                ProductTechStack.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert ts is not None and ts.dev_tools == "ruff, pytest, Vite"

    # ...and the staged sequence flipped the flag the wizard reads.
    await session.refresh(product)
    assert product.vision_analysis_complete is True


@pytest.mark.asyncio
async def test_a_second_staged_call_does_not_discard_empty_columns(product_context_client):
    """The museum-rule fix, verified through the transport rather than in-process:
    a repair call fills the still-empty columns of an already-touched block."""
    new_client, tenant_key, session = product_context_client
    product, _doc = await _seed(session, tenant_key)

    async with new_client() as mcp_session:
        await mcp_session.call_tool(
            "update_product_context",
            {"product_id": product.id, "tech_stack": {"programming_languages": "Python"}},
        )
        repair = await mcp_session.call_tool(
            "update_product_context",
            {"product_id": product.id, "tech_stack": {"infrastructure": "Docker", "dev_tools": "ruff"}},
        )
        assert repair.is_error is False, _error_text(repair)
        assert repair.structured_content["fields_skipped"] == []

    ts = (
        await session.execute(
            select(ProductTechStack).where(
                ProductTechStack.product_id == product.id,
                ProductTechStack.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert ts.infrastructure == "Docker"
    assert ts.dev_tools == "ruff"
    assert ts.programming_languages == "Python"
