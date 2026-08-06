# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Regression tests for BE-9322 DoD item 3: wire depth_tech_stack_sections.

A black-box QA harness (Suite A, 2026-07-31) measured that
``get_context(categories=['tech_stack'])`` returns byte-identical output for
'required' vs 'all'. Root cause: ``_fetch_category`` never forwarded a depth
override into ``get_tech_stack`` at all -- the category was lumped into the
same branch as ``architecture``/``testing`` with an explicit "No depth param"
comment.

(The companion ``depth_architecture`` control was found dead by the same
harness but is deliberately held unwired -- its stored default is "overview",
and honoring it would silently shrink every existing user's context. That is
a separate, not-yet-made product decision, not part of this fix.)

These tests exercise ``fetch_context()`` (the dispatcher), mocking the
category tool functions and asserting on the kwargs they were invoked with --
the exact same technique
``test_fetch_context_git_history_depth_string.py`` uses for the git_history
depth-parsing regression. This proves the WIRING: an explicit depth_config
override reaches ``get_tech_stack`` as ``sections``. The genuine-output-subset
proof (that 'required' actually drops fields) lives at the service layer in
``tests/services/test_get_tech_stack_depth.py`` since that requires real
product rows; a true MCP-transport boundary proof lives in
``tests/integration/test_be9322_context_depth_mcp_transport.py`` per the
CLAUDE.md rule that depth resolves at the get_context MCP boundary.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from giljo_mcp.tools.context_tools.fetch_context import fetch_context


fetch_context_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]

PRODUCT_ID = "11111111-1111-1111-1111-111111111111"
TENANT_KEY = "tk_test"


def _tech_stack_result() -> dict[str, Any]:
    return {"source": "tech_stack", "data": {"programming_languages": "Python"}, "metadata": {}}


async def _run_fetch(category: str, tool_result: dict[str, Any], depth_value: Any) -> tuple[dict[str, Any], AsyncMock]:
    tool = AsyncMock(return_value=tool_result)

    with (
        patch.dict(fetch_context_module.CATEGORY_TOOLS, {category: tool}),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(fetch_context_module, "_load_user_depth_config", new=AsyncMock(return_value={})),
        patch.object(fetch_context_module, "_build_last_modified_map", new=AsyncMock(return_value={})),
    ):
        response = await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=[category],
            depth_config={category: depth_value},
            db_manager=object(),  # truthy stand-in; real DB calls are patched
        )
    return response, tool


@pytest.mark.asyncio
async def test_tech_stack_depth_override_forwarded_as_sections():
    """BE-9322: depth_config={'tech_stack': 'required'} must reach get_tech_stack
    as sections='required', not be silently dropped (previous behavior: no
    depth kwarg was ever built for this category)."""
    response, tool = await _run_fetch("tech_stack", _tech_stack_result(), "required")

    assert "tech_stack" in response["categories_returned"]
    assert tool.await_count == 1
    assert tool.await_args.kwargs.get("sections") == "required", (
        f"'required' must reach get_tech_stack as sections=..., got kwargs={tool.await_args.kwargs!r}"
    )


@pytest.mark.asyncio
async def test_tech_stack_depth_all_forwarded_as_sections():
    """The 'all' value must also be forwarded (not just 'required') -- proves
    the wiring is a real passthrough, not a one-value special case."""
    response, tool = await _run_fetch("tech_stack", _tech_stack_result(), "all")

    assert "tech_stack" in response["categories_returned"]
    assert tool.await_args.kwargs.get("sections") == "all"


@pytest.mark.asyncio
async def test_architecture_category_still_receives_no_depth_param():
    """BE-9322 holds depth_architecture unwired on purpose (see module docstring)
    -- must keep its exact prior behavior: no depth kwarg at all, regardless of
    what depth_config carries."""
    tool = AsyncMock(return_value={"source": "architecture", "data": {}, "metadata": {}})

    with (
        patch.dict(fetch_context_module.CATEGORY_TOOLS, {"architecture": tool}),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(fetch_context_module, "_load_user_depth_config", new=AsyncMock(return_value={})),
        patch.object(fetch_context_module, "_build_last_modified_map", new=AsyncMock(return_value={})),
    ):
        await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=["architecture"],
            depth_config={"architecture": "detailed"},
            db_manager=object(),
        )

    assert "depth" not in tool.await_args.kwargs
    assert "sections" not in tool.await_args.kwargs


@pytest.mark.asyncio
async def test_testing_category_still_receives_no_depth_param():
    """Out of scope for BE-9322 (unlike tech_stack, 'testing' has no
    confirmed-dead control tied to it) -- must keep its exact prior behavior:
    no depth kwarg at all, regardless of what depth_config carries."""
    tool = AsyncMock(return_value={"source": "testing", "data": {}, "metadata": {}})

    with (
        patch.dict(fetch_context_module.CATEGORY_TOOLS, {"testing": tool}),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(fetch_context_module, "_load_user_depth_config", new=AsyncMock(return_value={})),
        patch.object(fetch_context_module, "_build_last_modified_map", new=AsyncMock(return_value={})),
    ):
        await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=["testing"],
            depth_config={"testing": "full"},
            db_manager=object(),
        )

    assert "depth" not in tool.await_args.kwargs
    assert "sections" not in tool.await_args.kwargs
