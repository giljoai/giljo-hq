# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import sys
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from giljo_mcp.tools.context_tools.fetch_context import fetch_context


fetch_context_module = sys.modules["giljo_mcp.tools.context_tools.fetch_context"]


PRODUCT_ID = "11111111-1111-1111-1111-111111111111"
TENANT_KEY = "tk_test"


def _git_history_result() -> dict[str, Any]:
    return {
        "source": "git_history",
        "data": [{"id": "abc123", "type": "commit", "message": "a commit"}],
        "metadata": {"git_integration_enabled": True, "returned_commits": 1},
    }


async def _run_fetch(depth_value: Any) -> tuple[dict[str, Any], AsyncMock]:
    git_tool = AsyncMock(return_value=_git_history_result())

    with (
        patch.dict(fetch_context_module.CATEGORY_TOOLS, {"git_history": git_tool}),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(fetch_context_module, "_load_user_depth_config", new=AsyncMock(return_value={})),
        patch.object(fetch_context_module, "_build_last_modified_map", new=AsyncMock(return_value={})),
    ):
        response = await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=["git_history"],
            depth_config={"git_history": depth_value},
            db_manager=object(),
        )
    return response, git_tool


@pytest.mark.asyncio
async def test_git_history_depth_summary_token_does_not_drop_category():
    response, git_tool = await _run_fetch("summary")

    failed = {e["category"] for e in response.get("errors", [])}
    assert "git_history" not in failed, (
        f"git_history must not fail on advertised string depth 'summary', errors={response.get('errors')}"
    )
    assert "git_history" in response["categories_returned"]
    assert git_tool.await_count == 1
    commits = git_tool.await_args.kwargs.get("commits")
    assert commits is None or isinstance(commits, int), (
        f"'summary' must map to an int commit count or fall back to the default, got {commits!r}"
    )


@pytest.mark.asyncio
async def test_git_history_depth_numeric_string_parses():
    response, git_tool = await _run_fetch("50")

    assert "git_history" in response["categories_returned"]
    assert response.get("errors") is None or not response["errors"]
    assert git_tool.await_args.kwargs.get("commits") == 50


@pytest.mark.asyncio
async def test_git_history_depth_unrecognized_string_is_refused():
    from giljo_mcp.exceptions import ValidationError

    with pytest.raises(ValidationError, match="git_history"):
        await _run_fetch("bogus-token")


@pytest.mark.asyncio
async def test_git_history_depth_int_unchanged_regression():
    response, git_tool = await _run_fetch(50)

    assert "git_history" in response["categories_returned"]
    assert git_tool.await_args.kwargs.get("commits") == 50
