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


def _stub_results() -> dict[str, dict[str, Any]]:
    return {
        "memory_360": {
            "source": "360_memory",
            "data": [],
            "metadata": {"total_projects": 0, "returned_projects": 0},
        },
        "git_history": {
            "source": "git_history",
            "data": [],
            "directive": {
                "action": "fetch_from_local_repo",
                "command": "git log --oneline -25",
                "note": "Git history is not stored on the server. Run this command in the project directory.",
            },
            "metadata": {"git_integration_enabled": False},
        },
        "vision_documents": {
            "source": "vision_document",
            "data": {"summary": "vision summary text", "sections": ["a", "b"]},
            "metadata": {"chunking": "medium"},
        },
    }


@pytest.mark.asyncio
async def test_empty_memory_360_appears_in_returned_and_empty_lists():
    stubs = _stub_results()

    async def fake_fetch(category: str, **_kwargs):
        return stubs[category]

    with (
        patch.object(fetch_context_module, "_fetch_category", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(
            fetch_context_module,
            "_load_user_depth_config",
            new=AsyncMock(return_value={}),
        ),
    ):
        response = await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=["memory_360", "git_history", "vision_documents"],
            db_manager=object(),
        )

    assert response["categories_requested"] == [
        "memory_360",
        "git_history",
        "vision_documents",
    ]
    assert "memory_360" in response["categories_returned"], (
        f"memory_360 must remain in categories_returned even with empty data, got: {response['categories_returned']}"
    )
    assert "categories_empty" in response, "response must expose categories_empty"
    assert "memory_360" in response["categories_empty"]
    assert "memory_360" in response["data"], "memory_360 must be present in data even when empty"
    assert response["data"]["memory_360"] == []


@pytest.mark.asyncio
async def test_directive_handled_git_history_still_in_returned():
    stubs = _stub_results()

    async def fake_fetch(category: str, **_kwargs):
        return stubs[category]

    with (
        patch.object(fetch_context_module, "_fetch_category", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(
            fetch_context_module,
            "_load_user_depth_config",
            new=AsyncMock(return_value={}),
        ),
    ):
        response = await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=["memory_360", "git_history", "vision_documents"],
            db_manager=object(),
        )

    assert "directive" in response
    assert "git_history" in response["directive"]
    assert response["directive"]["git_history"]["action"] == "fetch_from_local_repo"

    assert "git_history" in response["categories_returned"]
    assert "git_history" in response["data"]
    git_marker = response["data"]["git_history"]
    assert isinstance(git_marker, dict)
    assert git_marker.get("directive") is True


@pytest.mark.asyncio
async def test_populated_category_unchanged_regression():
    stubs = _stub_results()

    async def fake_fetch(category: str, **_kwargs):
        return stubs[category]

    with (
        patch.object(fetch_context_module, "_fetch_category", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(
            fetch_context_module,
            "_load_user_depth_config",
            new=AsyncMock(return_value={}),
        ),
    ):
        response = await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=["memory_360", "git_history", "vision_documents"],
            db_manager=object(),
        )

    assert "vision_documents" in response["categories_returned"]
    assert "vision_documents" not in response.get("categories_empty", [])
    assert response["data"]["vision_documents"] == {
        "summary": "vision summary text",
        "sections": ["a", "b"],
    }


@pytest.mark.asyncio
async def test_categories_returned_union_failed_equals_requested():
    stubs = _stub_results()

    async def fake_fetch(category: str, **_kwargs):
        return stubs[category]

    with (
        patch.object(fetch_context_module, "_fetch_category", new=AsyncMock(side_effect=fake_fetch)),
        patch.object(fetch_context_module, "_is_category_enabled", new=AsyncMock(return_value=True)),
        patch.object(
            fetch_context_module,
            "_load_user_depth_config",
            new=AsyncMock(return_value={}),
        ),
    ):
        response = await fetch_context(
            product_id=PRODUCT_ID,
            tenant_key=TENANT_KEY,
            categories=["memory_360", "git_history", "vision_documents"],
            db_manager=object(),
        )

    requested = set(response["categories_requested"])
    returned = set(response["categories_returned"])
    failed = {e["category"] for e in response.get("errors", [])}
    assert requested == returned | failed, (
        f"Contract violation: requested={requested} != returned={returned} union failed={failed}"
    )
