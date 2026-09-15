# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import json
import uuid
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._base import MCP_DESCRIPTION_MAX
from giljo_mcp.models import Product, VisionDocument
from giljo_mcp.models.products import ProductTechStack
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_REMOVED_FLAT_PARAMS: frozenset[str] = frozenset(
    {
        "programming_languages",
        "frontend_frameworks",
        "backend_frameworks",
        "databases",
        "infrastructure",
        "target_platforms",
        "architecture_pattern",
        "design_patterns",
        "api_style",
        "architecture_notes",
        "coding_conventions",
        "brand_guidelines",
        "quality_standards",
        "testing_strategy",
        "testing_frameworks",
        "test_coverage_target",
    }
)

_GROUPED_PARAMS: frozenset[str] = frozenset({"tech_stack", "architecture", "quality", "testing"})

_LEAK_MARKERS = ("[SQL:", "[parameters:", "Traceback", "INSERT INTO", "psycopg")


def _error_text(result) -> str:
    parts = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _assert_structured_validation_rejection(result) -> None:
    assert result.is_error is False, _error_text(result)
    payload = json.loads(result.content[0].text)
    assert payload.get("success") is False, payload
    assert payload.get("error") == "VALIDATION_ERROR", payload
    assert payload.get("field"), payload


def _assert_no_leak(text: str) -> None:
    for marker in _LEAK_MARKERS:
        assert marker not in text, f"agent-facing error leaked {marker!r}: {text!r}"


def _live_update_product_context_params() -> set[str]:
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "update_product_context":
            return set(tool.parameters.get("properties", {}).keys())
    raise AssertionError("update_product_context not registered on the live FastMCP surface")


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


@pytest.mark.asyncio
async def test_grouped_call_dispatches(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "update_product_context",
            {
                "product_id": str(uuid.uuid4()),
                "tech_stack": {"programming_languages": "Python, TypeScript", "target_platforms": ["web"]},
                "architecture": {"api_style": "REST", "architecture_pattern": "layered"},
                "quality": {"quality_standards": "WCAG AA, 90% coverage"},
                "testing": {"testing_strategy": "TDD", "test_coverage_target": 90},
            },
        )
    assert result.is_error is False, f"valid grouped call must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_grouped_over_cap_field_is_clean_422(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "update_product_context",
            {
                "product_id": str(uuid.uuid4()),
                "tech_stack": {"programming_languages": "x" * (MCP_DESCRIPTION_MAX + 1)},
            },
        )
    _assert_structured_validation_rejection(result)
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_unknown_group_subkey_is_clean_422(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "update_product_context",
            {"product_id": str(uuid.uuid4()), "tech_stack": {"quality_standards": "wrong group"}},
        )
    _assert_structured_validation_rejection(result)
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_apply_context_tuning_valid_typed_proposal_dispatches(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid.uuid4()),
                "proposals": [
                    {
                        "section": "description",
                        "drift_detected": True,
                        "proposed_value": "An updated description.",
                        "confidence": "high",
                    }
                ],
            },
        )
    assert result.is_error is False, f"valid typed proposal must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_apply_context_tuning_malformed_proposal_is_clean_422(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {"product_id": str(uuid.uuid4()), "proposals": [{"section": "description"}]},
        )
    _assert_structured_validation_rejection(result)
    text = _error_text(result)
    _assert_no_leak(text)
    assert "drift_detected" in text


@pytest.mark.asyncio
async def test_apply_context_tuning_over_cap_proposed_value_is_clean_422(autospec_mcp):
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid.uuid4()),
                "proposals": [{"section": "description", "drift_detected": True, "proposed_value": "x" * 10_001}],
            },
        )
    _assert_structured_validation_rejection(result)
    _assert_no_leak(_error_text(result))


@pytest_asyncio.fixture
async def product_context_client(db_manager, db_session, monkeypatch):
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


@pytest.mark.asyncio
async def test_single_grouped_call_flips_vision_complete_atomically(product_context_client):
    new_client, tenant_key, session = product_context_client
    product = Product(
        id=str(uuid.uuid4()),
        name="BE-9118 atomic",
        description="single-call flip",
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
        document_name="Vision",
        document_type="vision",
        vision_document="Vision content for BE-9118 atomic test.",
        storage_type="inline",
        content_hash="be9118hash",
        is_active=True,
        display_order=0,
        version="1.0.0",
        chunked=False,
        chunk_count=0,
    )
    session.add(doc)
    await session.flush()

    async with new_client() as mcp_session:
        result = await mcp_session.call_tool(
            "update_product_context",
            {
                "product_id": product.id,
                "tech_stack": {"programming_languages": "Python"},
                "vision_summaries": [{"doc_id": doc.id, "light": "Light summary.", "medium": "Medium summary."}],
                "consolidated_vision": {"light": "Consolidated light.", "medium": "Consolidated medium."},
            },
        )
    assert result.is_error is False, f"atomic grouped call must dispatch: {_error_text(result)}"

    ts = (
        await session.execute(
            select(ProductTechStack).where(
                ProductTechStack.product_id == product.id,
                ProductTechStack.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert ts is not None and ts.programming_languages == "Python"

    await session.refresh(product)
    assert product.vision_analysis_complete is True


_REPO_ROOT = Path(__file__).resolve().parents[2]
_ONBOARDING_JS = _REPO_ROOT / "frontend" / "src" / "composables" / "useVisionAnalysis.js"


def _onboarding_prompt_region() -> str:
    text = _ONBOARDING_JS.read_text(encoding="utf-8")
    start = text.index("let prompt =")
    end = text.index("promptFallbackText.value = null", start)
    return text[start:end]


def test_onboarding_prompt_only_references_live_update_product_context_params():
    from giljo_mcp.tools.vision_analysis import VISION_EXTRACTION_PROMPT

    live = _live_update_product_context_params()
    assert not (_REMOVED_FLAT_PARAMS & live), f"flat params still on the live schema: {_REMOVED_FLAT_PARAMS & live}"

    region = _onboarding_prompt_region()
    leaked = sorted(name for name in _REMOVED_FLAT_PARAMS if name in region)
    assert not leaked, f"wizard prompt references removed flat param(s) (regrouped in BE-9118): {leaked}"
    assert "extraction_instructions" in region, (
        "wizard prompt must defer to get_vision_document's extraction_instructions (BE-9164) instead of naming params itself"
    )

    missing = sorted(name for name in _GROUPED_PARAMS if name not in VISION_EXTRACTION_PROMPT)
    assert not missing, f"VISION_EXTRACTION_PROMPT must name the grouped params it instructs: missing {missing}"
    assert live >= _GROUPED_PARAMS

    leaked_server = sorted(name for name in _REMOVED_FLAT_PARAMS if f"{name}=" in VISION_EXTRACTION_PROMPT)
    assert not leaked_server, (
        f"VISION_EXTRACTION_PROMPT references removed flat param(s) as a top-level "
        f"kwarg (regrouped in BE-9118): {leaked_server}"
    )


def test_update_product_context_wrapper_has_zero_toggle_linkage():
    import api.endpoints.mcp_tools._context_tools as ct

    fn = next(t.fn for t in mcp._tool_manager.list_tools() if t.name == "update_product_context")
    sources = [inspect.getsource(fn)]
    for symbol in (
        ct._TechStackContext,
        ct._ArchitectureContext,
        ct._QualityContext,
        ct._TestingContext,
        ct._merge_group,
    ):
        sources.append(inspect.getsource(symbol))
    src = "\n".join(sources)

    forbidden = (
        "UserFieldPriority",
        "depth_config",
        "field_prioriti",
        "toggle_config",
        "TUNING_SECTION_TOGGLE_MAP",
        "get_eligible_sections",
        "depth_vision",
    )
    hits = [token for token in forbidden if token in src]
    assert not hits, f"update_product_context wrapper gained UI-toggle linkage: {hits}"


def test_toggle_gate_still_excludes_a_toggled_off_category():
    from unittest.mock import MagicMock

    from giljo_mcp.services.product_tuning_service import ProductTuningService

    service = ProductTuningService(db_manager=MagicMock(), tenant_key="t")
    on = service._get_eligible_sections({"priorities": {"tech_stack": {"toggle": True}}})
    off = service._get_eligible_sections({"priorities": {"tech_stack": {"toggle": False}}})
    tech_sections = {s for s in on if s.startswith("tech_stack")}
    assert tech_sections, "expected tech_stack sections eligible when toggled on"
    assert not (tech_sections & set(off)), "toggled-off tech_stack sections must be excluded"
