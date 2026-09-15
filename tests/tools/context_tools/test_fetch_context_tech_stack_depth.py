# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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
            db_manager=object(),
        )
    return response, tool


@pytest.mark.asyncio
async def test_tech_stack_depth_override_forwarded_as_sections():
    response, tool = await _run_fetch("tech_stack", _tech_stack_result(), "required")

    assert "tech_stack" in response["categories_returned"]
    assert tool.await_count == 1
    assert tool.await_args.kwargs.get("sections") == "required", (
        f"'required' must reach get_tech_stack as sections=..., got kwargs={tool.await_args.kwargs!r}"
    )


@pytest.mark.asyncio
async def test_tech_stack_depth_all_forwarded_as_sections():
    response, tool = await _run_fetch("tech_stack", _tech_stack_result(), "all")

    assert "tech_stack" in response["categories_returned"]
    assert tool.await_args.kwargs.get("sections") == "all"


@pytest.mark.asyncio
async def test_architecture_category_still_receives_no_depth_param():
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
