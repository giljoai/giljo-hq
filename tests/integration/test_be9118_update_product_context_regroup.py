# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9118 (Option B) — update_product_context regroup + apply_context_tuning typed
proposals, tested at the layer the change lives (the FastMCP @mcp.tool wrapper).

CLAUDE.md + the BE-5042 lesson mandate MCP-BOUNDARY tests: the regroup is a
wrapper-only change (17 flat prose params -> 4 typed grouped dicts, unpacked to the
SAME flat ProductService kwargs), so every behavioral test here drives the REAL
transport (``create_connected_server_and_client_session``), not the service in
isolation. Sections map to the product's 4 hard invariants:

* Section A (autospec transport, no DB) — invariant 4 (input validation preserved):
  a valid grouped call dispatches; an over-cap grouped field and an unknown grouped
  sub-key are each a clean 422-style ToolError with no SQL/leak; the apply_context_
  tuning typed-proposal boundary (SCOPE 2) accepts a well-formed item and rejects a
  structurally malformed one at the boundary (the NEW Pydantic rejection shape).
* Section B (DB-backed transport) — invariant 3 (single-atomic-call preserved): one
  grouped-dict call carrying vision_summaries + consolidated_vision writes the
  grouped field AND flips vision_analysis_complete in one transaction.
* Section C (unit) — invariant 2 (onboarding drift) + invariant 1 (UI-toggle
  isolation): the copy-to-clipboard onboarding prompt references only params that
  exist on the live tool schema, and the regrouped wrapper has zero linkage to the
  UI context-depth toggle machinery.

Parallel-safe: Section A/C need no DB; Section B uses the rolled-back ``db_session``
threaded through the tool via a monkeypatched ``update_product_fields``. No
module-level mutable state; tenant keys are freshly generated per test.
"""

from __future__ import annotations

import inspect
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


# The 17 flat prose params BE-9118 regrouped into the tech_stack/architecture/
# quality/testing dicts. None may survive as a top-level update_product_context
# param, nor be advertised as a call param by the onboarding prompt.
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


def _assert_no_leak(text: str) -> None:
    for marker in _LEAK_MARKERS:
        assert marker not in text, f"agent-facing error leaked {marker!r}: {text!r}"


def _live_update_product_context_params() -> set[str]:
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "update_product_context":
            return set(tool.parameters.get("properties", {}).keys())
    raise AssertionError("update_product_context not registered on the live FastMCP surface")


# ---------------------------------------------------------------------------
# Section A — autospec transport (no DB): grouped-dict arg validation + the
# apply_context_tuning typed-proposal boundary.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    """Autospec ToolAccessor on the in-memory transport (mirrors BE-3006d)."""
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
    """INVARIANT 4 (positive): a valid grouped-dict call passes arg validation and
    dispatches (isError False)."""
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
    """INVARIANT 4: an over-cap prose field INSIDE a group is rejected at the
    FastMCP boundary as a clean 422, never a service 500 / DB leak."""
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "update_product_context",
            {
                "product_id": str(uuid.uuid4()),
                "tech_stack": {"programming_languages": "x" * (MCP_DESCRIPTION_MAX + 1)},
            },
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_unknown_group_subkey_is_clean_422(autospec_mcp):
    """INVARIANT 4: extra='forbid' on each grouped model rejects an unknown sub-key
    (e.g. a flat field placed in the wrong group) as a clean 422, no leak."""
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "update_product_context",
            {"product_id": str(uuid.uuid4()), "tech_stack": {"quality_standards": "wrong group"}},
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


@pytest.mark.asyncio
async def test_apply_context_tuning_valid_typed_proposal_dispatches(autospec_mcp):
    """SCOPE 2 (positive): a well-formed typed proposal passes the Pydantic boundary
    and dispatches."""
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
    """SCOPE 2 (new rejection shape): a structurally malformed proposal (missing the
    required drift_detected) is rejected at the FastMCP/Pydantic boundary as a clean
    422 — the typed-model rejection replaces the service's aggregated ValueError for
    this class of error. No SQL/leak."""
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {"product_id": str(uuid.uuid4()), "proposals": [{"section": "description"}]},
        )
    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    # The Pydantic boundary names the missing required field (the new shape).
    assert "drift_detected" in text


@pytest.mark.asyncio
async def test_apply_context_tuning_over_cap_proposed_value_is_clean_422(autospec_mcp):
    """SCOPE 2: the pre-typed 10000-char proposed_value cap is preserved on the
    typed model — an over-cap string is a clean 422 at the boundary."""
    async with autospec_mcp() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid.uuid4()),
                "proposals": [{"section": "description", "drift_detected": True, "proposed_value": "x" * 10_001}],
            },
        )
    assert result.is_error is True
    _assert_no_leak(_error_text(result))


# ---------------------------------------------------------------------------
# Section B — DB-backed transport: the single-atomic-call invariant.
# ---------------------------------------------------------------------------
@pytest_asyncio.fixture
async def product_context_client(db_manager, db_session, monkeypatch):
    """A REAL ToolAccessor on the transport, with update_product_fields threaded
    onto the rolled-back test session (the accessor mixin does not forward
    _test_session, so inject it via a module-level monkeypatch — the mixin imports
    the symbol at call time)."""
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
    """INVARIANT 3: ONE grouped-dict update_product_context call carrying a grouped
    field + per-doc vision_summaries + consolidated_vision writes the grouped field
    AND flips vision_analysis_complete (the wizard-unlock) in one transaction."""
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

    # The grouped field unpacked and wrote to the tech_stack child row...
    ts = (
        await session.execute(
            select(ProductTechStack).where(
                ProductTechStack.product_id == product.id,
                ProductTechStack.tenant_key == tenant_key,
            )
        )
    ).scalar_one_or_none()
    assert ts is not None and ts.programming_languages == "Python"

    # ...and the same single call flipped vision_analysis_complete (the wizard unlock).
    await session.refresh(product)
    assert product.vision_analysis_complete is True


# ---------------------------------------------------------------------------
# Section C — unit: onboarding drift (invariant 2) + UI-toggle isolation (invariant 1).
# ---------------------------------------------------------------------------
_REPO_ROOT = Path(__file__).resolve().parents[2]
_ONBOARDING_JS = _REPO_ROOT / "frontend" / "src" / "composables" / "useVisionAnalysis.js"


def _onboarding_prompt_region() -> str:
    """The copy-to-clipboard discovery prompt text built in stageAnalysis()."""
    text = _ONBOARDING_JS.read_text(encoding="utf-8")
    start = text.index("let prompt =")
    end = text.index("promptFallbackText.value = null", start)
    return text[start:end]


def test_onboarding_prompt_only_references_live_update_product_context_params():
    """INVARIANT 2 (drift): the instruction authority for update_product_context's
    param shape may only name params that exist on the live tool schema. Because
    FastMCP silently DROPS an unknown top-level arg, an instruction that still named
    a removed flat param would cause silent data loss.

    BE-9164 superseded the BE-5118-era wizard prompt as that authority: the wizard
    prompt (useVisionAnalysis.js) is now a slim pointer at get_vision_document's
    extraction_instructions, and VISION_EXTRACTION_PROMPT (server-side, in
    giljo_mcp.tools.vision_analysis) is the single source of truth for the param
    shape. So the guard splits in two:
    - the wizard prompt must still never leak a removed flat param (it could
      resurrect the drift even without naming grouped params), and must defer to
      the server instructions instead of naming params itself;
    - VISION_EXTRACTION_PROMPT must name all 4 grouped params and never leak a
      removed flat param as a top-level kwarg.

    Fail-first: re-insert e.g. 'programming_languages=' into either prompt, or
    delete 'tech_stack'/'architecture'/'quality'/'testing' from
    VISION_EXTRACTION_PROMPT, and this trips.
    """
    from giljo_mcp.tools.vision_analysis import VISION_EXTRACTION_PROMPT

    live = _live_update_product_context_params()
    # The regroup actually happened: no removed flat name survives as a live param.
    assert not (_REMOVED_FLAT_PARAMS & live), f"flat params still on the live schema: {_REMOVED_FLAT_PARAMS & live}"

    # -- Wizard prompt (useVisionAnalysis.js): no longer the instruction authority.
    # It must never leak a removed flat param, and must defer to the server prompt.
    region = _onboarding_prompt_region()
    leaked = sorted(name for name in _REMOVED_FLAT_PARAMS if name in region)
    assert not leaked, f"wizard prompt references removed flat param(s) (regrouped in BE-9118): {leaked}"
    assert "extraction_instructions" in region, (
        "wizard prompt must defer to get_vision_document's extraction_instructions (BE-9164) instead of naming params itself"
    )

    # -- Server prompt (VISION_EXTRACTION_PROMPT): the real instruction authority.
    # Must name all 4 grouped params...
    missing = sorted(name for name in _GROUPED_PARAMS if name not in VISION_EXTRACTION_PROMPT)
    assert not missing, f"VISION_EXTRACTION_PROMPT must name the grouped params it instructs: missing {missing}"
    # Every grouped name the prompt uses is a real live param.
    assert live >= _GROUPED_PARAMS

    # ...and must never leak a removed flat name as a TOP-LEVEL kwarg. The grouped
    # call example legitimately contains these names as dict sub-keys, e.g.
    # tech_stack={"programming_languages": "..."} -- that renders as
    # '"programming_languages":' in the prompt text, never 'programming_languages='.
    # So checking for the '=' call-site form (not bare substring containment)
    # correctly allows the sub-key usage while still catching a real top-level leak.
    leaked_server = sorted(name for name in _REMOVED_FLAT_PARAMS if f"{name}=" in VISION_EXTRACTION_PROMPT)
    assert not leaked_server, (
        f"VISION_EXTRACTION_PROMPT references removed flat param(s) as a top-level "
        f"kwarg (regrouped in BE-9118): {leaked_server}"
    )


def test_update_product_context_wrapper_has_zero_toggle_linkage():
    """INVARIANT 1 (UI context-depth toggles untouched): the regrouped
    update_product_context wrapper + its 4 grouped models + the unpack helper carry
    ZERO linkage to the read-side toggle/depth machinery (UserFieldPriority,
    depth_config, tuning toggle map). Scoped to exactly the BE-9118 surface via
    getsource (the sibling get_context tool in the same module legitimately uses
    depth_config for READS and is untouched). A future edit wiring toggles into the
    write path trips this guard."""
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
    """INVARIANT 1 (supporting): the read-side toggle gate is unperturbed — a
    category toggled OFF is excluded from tuning-eligible sections exactly as
    before (the SCOPE-2 typed-proposals change did not touch this path)."""
    from unittest.mock import MagicMock

    from giljo_mcp.services.product_tuning_service import ProductTuningService

    service = ProductTuningService(db_manager=MagicMock(), tenant_key="t")
    on = service._get_eligible_sections({"priorities": {"tech_stack": {"toggle": True}}})
    off = service._get_eligible_sections({"priorities": {"tech_stack": {"toggle": False}}})
    tech_sections = {s for s in on if s.startswith("tech_stack")}
    assert tech_sections, "expected tech_stack sections eligible when toggled on"
    assert not (tech_sections & set(off)), "toggled-off tech_stack sections must be excluded"
