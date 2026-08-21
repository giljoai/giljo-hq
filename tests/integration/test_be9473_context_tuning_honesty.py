# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9473 -- apply_context_tuning states its limits up front and fails loudly.

A real-world agent using apply_context_tuning paid a 9-attempt tax (7 avoidable)
because the tool taught its rules by rejecting rather than describing. Four
findings, tested at the layer each one actually lives:

* F1 (wire description) -- the ``force`` param's Field description must name the
  overwrite rule, and a service-layer ValidationError must still reach the agent
  unmangled (BE-3006d two-tier boundary, unchanged by this project -- pinned here
  for apply_context_tuning specifically).
* F2 (structure before size) -- a STRUCTURED section (tech_stack/architecture)
  sent as a flat string must be rejected with the sub-key remedy REGARDLESS of
  length, not gated behind a shrinking length error.
* F3 (no silent no-op success) -- see
  tests/services/test_product_tuning_service.py::TestApplyTuningUpdates::
  test_all_drift_sections_unresolved_declines_instead_of_success (service-layer
  fix, service-layer regression test per house rule).
* F4 (wire caps) -- the proposals Field description states FLAT vs STRUCTURED
  sections, the per-sub-key cap, and the sub-key addressing convention.

CLAUDE.md mandates a regression test at the failing layer: F1/F2/F4 are wire
(FastMCP @mcp.tool arg-validation) bugs, so every test here drives the REAL
transport (``create_connected_server_and_client_session``), mirroring
tests/integration/test_be3006d_mcp_boundary_validation.py and
tests/integration/test_be9118_update_product_context_regroup.py.

Parallel-safe: no DB, no module-level mutable state; tenant keys are freshly
generated per test.
"""

from __future__ import annotations

import inspect
from unittest.mock import create_autospec
from uuid import uuid4

import pytest
import pytest_asyncio

from api.endpoints.mcp_sdk_server import mcp
from giljo_mcp.exceptions import ValidationError as GiljoValidationError
from giljo_mcp.services.product_tuning_service import TUNING_PROPOSED_VALUE_MAX
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


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


def _apply_context_tuning_schema() -> dict:
    for tool in mcp._tool_manager.list_tools():
        if tool.name == "apply_context_tuning":
            return tool.parameters
    raise AssertionError("apply_context_tuning not found in the live tool registry")


# ---------------------------------------------------------------------------
# F1 + F4 -- wire delivery (schema pin, BE-9469 TestListProjectsSchemaDeclarations
# template). A description that exists in source but never reaches the wire is
# the exact defect BE-9470 shipped to fix elsewhere.
# ---------------------------------------------------------------------------


class TestApplyContextTuningSchemaDeclarations:
    def test_force_description_names_the_overwrite_rule(self):
        """F1: force is the flag an agent almost always needs on a populated
        product (the common case), and it was undocumented on the wire."""
        schema = _apply_context_tuning_schema()
        description = schema["properties"]["force"].get("description", "")
        assert "force" in description.lower()
        assert "populated" in description.lower()

    def test_proposals_description_names_flat_vs_structured_sections(self):
        """F4: FLAT sections take a plain string; STRUCTURED sections
        (tech_stack, architecture) must be addressed by sub-key or dict."""
        schema = _apply_context_tuning_schema()
        description = schema["properties"]["proposals"].get("description", "")
        for term in ("FLAT", "STRUCTURED", "tech_stack", "architecture", "sub-key"):
            assert term in description, f"proposals description does not name {term!r}"

    def test_proposals_description_states_the_per_subkey_char_cap(self):
        """F4: the char limit is PER SUB-KEY, not per whole submission -- and
        must not silently drift from the enforced value."""
        schema = _apply_context_tuning_schema()
        description = schema["properties"]["proposals"].get("description", "")
        assert str(TUNING_PROPOSED_VALUE_MAX) in description
        assert "PER STRING" in description or "per sub-key" in description


# ---------------------------------------------------------------------------
# Autospec transport (no DB) -- F1 unmangled passthrough + F2 structure-first.
# ---------------------------------------------------------------------------


@pytest_asyncio.fixture
async def autospec_mcp(monkeypatch):
    """Install an autospec ToolAccessor + tenant resolution on the in-memory
    transport (mirrors BE-3006d / BE-9118). apply_context_tuning is an ADAPTER
    tool (absent from TOOL_DISPATCH), so it resolves through the accessor's own
    mixin method -- an autospec'd coroutine we can plant a side_effect on."""
    from api import app_state
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

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

    state.tool_accessor = accessor
    state.tenant_manager = TenantManager()
    state.db_manager = None

    tenant_key = TenantManager.generate_tenant_key()
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp)

    try:
        yield _client, accessor
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


@pytest.mark.asyncio
async def test_force_required_validation_error_reaches_agent_unmangled(autospec_mcp):
    """F1: ProductService.update_product's 'Fields already populated ... Pass
    force=True to overwrite' message (a curated ValidationError, 4xx) must
    surface VERBATIM through the MCP boundary, not be sanitized away."""
    client, accessor = autospec_mcp
    accessor.apply_context_tuning.side_effect = GiljoValidationError(
        message=("Fields already populated: tech_stack: infrastructure. Pass force=True to overwrite."),
        context={"populated_fields": ["tech_stack"], "product_id": "prod-1"},
    )

    async with client() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid4()),
                "proposals": [
                    {
                        "section": "tech_stack.infrastructure",
                        "drift_detected": True,
                        "proposed_value": "Terraform on AWS",
                    }
                ],
            },
        )

    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    assert "Fields already populated" in text
    assert "force=True" in text


@pytest.mark.asyncio
async def test_structured_section_flat_string_rejected_regardless_of_length(autospec_mcp):
    """F2 (RED before the fix / GREEN after): a STRUCTURED section sent as a
    flat string must be rejected with the sub-key remedy on the FIRST call --
    for a SHORT string too, proving this is a shape check, not a relabeled
    length check. The agent's actual repro used an over-length string; a short
    one isolates the shape defect from the (also present, separately capped)
    length rule."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid4()),
                "proposals": [
                    {
                        "section": "tech_stack",
                        "drift_detected": True,
                        "proposed_value": "FastAPI, Django",  # 15 chars -- well under any cap
                    }
                ],
            },
        )
    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    assert "sub-key" in text or "sub_key" in text
    assert "tech_stack.infrastructure" in text or "tech_stack." in text
    # The RED-state failure mode this proves absent: a shape problem must not be
    # reported as a length problem.
    assert "character limit" not in text


@pytest.mark.asyncio
async def test_structured_section_oversized_string_reports_shape_not_length(autospec_mcp):
    """F2, the agent's exact repro shape: an OVER-LENGTH string for a
    STRUCTURED section must still report the sub-key remedy first (structure
    before size), not '13467/10000 chars exceeded' -- the six-attempt tax this
    project exists to delete."""
    client, _accessor = autospec_mcp
    oversized = "FastAPI, Django, " * 800  # > 10_000 chars
    assert len(oversized) > TUNING_PROPOSED_VALUE_MAX
    async with client() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid4()),
                "proposals": [{"section": "architecture", "drift_detected": True, "proposed_value": oversized}],
            },
        )
    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    assert "sub-key" in text
    assert "architecture.primary_pattern" in text or "architecture." in text


@pytest.mark.asyncio
async def test_unknown_dict_subkey_for_structured_section_is_clean_422(autospec_mcp):
    """F2/pre-ruling #5: a dict value for a structured section must have its
    keys membership-checked at the boundary, not trusted through to the DB."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid4()),
                "proposals": [
                    {
                        "section": "tech_stack",
                        "drift_detected": True,
                        "proposed_value": {"not_a_real_field": "x"},
                    }
                ],
            },
        )
    assert result.is_error is True
    text = _error_text(result)
    _assert_no_leak(text)
    assert "unknown sub-key" in text


@pytest.mark.asyncio
async def test_flat_section_valid_short_string_still_dispatches(autospec_mcp):
    """Positive control: a FLAT section with a normal short string is untouched
    by the F2 shape check and still dispatches."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid4()),
                "proposals": [
                    {"section": "description", "drift_detected": True, "proposed_value": "An updated description."}
                ],
            },
        )
    assert result.is_error is False, f"valid flat proposal must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_structured_section_valid_subkey_dotted_form_still_dispatches(autospec_mcp):
    """Positive control: the documented remedy (dotted sub-key) must itself
    dispatch cleanly."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid4()),
                "proposals": [
                    {
                        "section": "tech_stack.infrastructure",
                        "drift_detected": True,
                        "proposed_value": "Terraform on AWS",
                    }
                ],
            },
        )
    assert result.is_error is False, f"valid dotted sub-key proposal must dispatch: {_error_text(result)}"


@pytest.mark.asyncio
async def test_structured_section_valid_dict_form_still_dispatches(autospec_mcp):
    """Positive control: the documented remedy (dict keyed by field name) must
    itself dispatch cleanly."""
    client, _accessor = autospec_mcp
    async with client() as session:
        result = await session.call_tool(
            "apply_context_tuning",
            {
                "product_id": str(uuid4()),
                "proposals": [
                    {
                        "section": "architecture",
                        "drift_detected": True,
                        "proposed_value": {"primary_pattern": "modular monolith"},
                    }
                ],
            },
        )
    assert result.is_error is False, f"valid dict-form proposal must dispatch: {_error_text(result)}"
