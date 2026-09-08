# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9523c -- giljo_setup's per-repo product binding, at the instruction-content layer.

Product identity chain step c: giljo_setup gains a phase-aware product binding
so a repo remembers which Giljo HQ product it belongs to, closing the loop BE-9523b
opened (its PRODUCT_AMBIGUOUS rejection tells the agent to come here).

These tests exercise ``build_setup_instructions`` (and its ``ProductBindingContext``
parameter) directly -- a pure function, no DB -- because the phase-resolution DB
logic lives one layer up in ``bootstrap_setup`` (covered separately at the MCP
boundary and by a DB-backed accessor test).
"""

from __future__ import annotations

from giljo_mcp.tools.setup_instructions import (
    GILJOAI_MCP_PRIMER,
    ProductBindingContext,
    build_setup_instructions,
)


_URL = "https://example.com/download/test"
_PRODUCT_ID = "9c6a6b1e-5a2e-4b7b-9a1a-111111111111"
_PRODUCT_NAME = "Giljo Agent Message Hub"


def test_bound_phase_writes_marker_block_naming_product_and_uuid():
    """A resolved product renders the GILJO_PRODUCT_BINDING block with name + id."""
    binding = ProductBindingContext(phase="bound", product_id=_PRODUCT_ID, product_name=_PRODUCT_NAME)
    result = build_setup_instructions("claude_code", _URL, product_binding=binding)

    assert "<!-- GILJO_PRODUCT_BINDING_START -->" in result
    assert "<!-- GILJO_PRODUCT_BINDING_END -->" in result
    assert _PRODUCT_NAME in result
    assert _PRODUCT_ID in result
    assert "Pass this product_id on every giljo_hq call." in result
    # Both boot files, not one -- CLAUDE.md and AGENTS.md are read by different clients.
    assert "CLAUDE.md" in result
    assert "AGENTS.md" in result


def test_bound_phase_marker_block_is_separate_from_the_frozen_primer_block():
    """The binding markers are namespaced apart from the frozen per-machine PRIMER markers."""
    binding = ProductBindingContext(phase="bound", product_id=_PRODUCT_ID, product_name=_PRODUCT_NAME)
    result = build_setup_instructions("claude_code", _URL, product_binding=binding)

    assert "GILJOAI_MCP_PRIMER_START" in result
    assert "GILJOAI_MCP_PRIMER_END" in result
    # The primer body itself must be byte-identical and untouched by the binding feature.
    assert GILJOAI_MCP_PRIMER in result
    # The binding block must never nest inside the primer markers.
    primer_start = result.index("GILJOAI_MCP_PRIMER_START")
    primer_end = result.index("GILJOAI_MCP_PRIMER_END")
    binding_start = result.index("GILJO_PRODUCT_BINDING_START")
    assert not (primer_start < binding_start < primer_end), "binding block must not nest inside the primer"


def test_zero_products_phase_never_blocks_setup_and_says_so():
    """Onboarding with no product yet is legal: setup still runs, no binding block."""
    binding = ProductBindingContext(phase="zero")
    result = build_setup_instructions("claude_code", _URL, product_binding=binding)

    assert "<!-- GILJO_PRODUCT_BINDING_START -->" not in result
    assert "no giljo hq product exists yet" in result.lower()
    assert "product_id" in result
    # Setup itself must still be fully present (skills/agents/primer), not short-circuited.
    assert GILJOAI_MCP_PRIMER in result
    assert _URL in result


def test_ambiguous_phase_lists_products_and_defers_to_user_confirmation():
    """Multiple products + no product_id: list them, never guess which one to bind."""
    products = (
        {"id": "aaaaaaaa-0000-0000-0000-000000000001", "name": "Giljo HQ", "is_active": True},
        {"id": "bbbbbbbb-0000-0000-0000-000000000002", "name": "Giljo Agent Message Hub", "is_active": False},
    )
    binding = ProductBindingContext(phase="ambiguous", products=products)
    result = build_setup_instructions("claude_code", _URL, product_binding=binding)

    assert "<!-- GILJO_PRODUCT_BINDING_START -->" not in result, "must never guess-write a binding"
    for p in products:
        assert p["id"] in result
        assert p["name"] in result
    assert "confirm" in result.lower()


def test_ambiguous_and_bound_wording_agrees_with_product_ambiguous_rejection():
    """DoD: step b's rejection text and this block's wording must agree (one sentence, both lanes sign it)."""
    from giljo_mcp.services.product_service import ProductAmbiguousError

    rejection = ProductAmbiguousError(
        products=[{"id": _PRODUCT_ID, "name": _PRODUCT_NAME, "is_active": True}],
        operation="create_project",
        tenant_key="tenant-x",
    )
    shared_phrase = "writes the binding into CLAUDE.md/AGENTS.md so this never asks again"
    assert shared_phrase in str(rejection)

    bound = ProductBindingContext(phase="bound", product_id=_PRODUCT_ID, product_name=_PRODUCT_NAME)
    result = build_setup_instructions("claude_code", _URL, product_binding=bound)
    assert shared_phrase in result or "so this never asks again" in result


def test_no_binding_context_is_a_byte_identical_no_op():
    """Callers that never pass product_binding (pre-existing tests) see no change at all."""
    with_none = build_setup_instructions("claude_code", _URL, product_binding=None)
    without_arg = build_setup_instructions("claude_code", _URL)
    assert with_none == without_arg
    assert "GILJO_PRODUCT_BINDING" not in with_none


def test_rerunning_bound_phase_twice_is_byte_identical_idempotent():
    """DoD: running setup twice with the same resolved product produces byte-identical output."""
    binding = ProductBindingContext(phase="bound", product_id=_PRODUCT_ID, product_name=_PRODUCT_NAME)
    first = build_setup_instructions("claude_code", _URL, product_binding=binding)
    second = build_setup_instructions("claude_code", _URL, product_binding=binding)
    assert first == second


def test_rename_updates_block_in_place_not_a_new_platform_string_shape():
    """DoD: a renamed product's re-run swaps the name only -- one block, not a stacked duplicate."""
    before = ProductBindingContext(phase="bound", product_id=_PRODUCT_ID, product_name="Old Name")
    after = ProductBindingContext(phase="bound", product_id=_PRODUCT_ID, product_name="New Name")

    result_before = build_setup_instructions("claude_code", _URL, product_binding=before)
    result_after = build_setup_instructions("claude_code", _URL, product_binding=after)

    assert result_before.count("<!-- GILJO_PRODUCT_BINDING_START -->") == 1
    assert result_after.count("<!-- GILJO_PRODUCT_BINDING_START -->") == 1
    assert "Old Name" in result_before and "Old Name" not in result_after
    assert "New Name" in result_after


def test_all_local_platforms_carry_the_binding_step_when_bound():
    """Every filesystem-writing platform branch gets the same binding step (no per-platform drift)."""
    binding = ProductBindingContext(phase="bound", product_id=_PRODUCT_ID, product_name=_PRODUCT_NAME)
    for platform in ("claude_code", "gemini_cli", "codex_cli", "antigravity_cli", "opencode", "generic"):
        result = build_setup_instructions(platform, _URL, product_binding=binding)
        assert "<!-- GILJO_PRODUCT_BINDING_START -->" in result, f"{platform} missing the binding block"
        assert _PRODUCT_ID in result, f"{platform} missing the product_id"
