# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from api.endpoints.mcp_sdk_server import mcp


def _description(name: str) -> str:
    tool = mcp._tool_manager.get_tool(name)
    assert tool is not None, name
    return tool.description or ""


@pytest.mark.parametrize("tool_name", ["post_to_thread", "create_thread", "set_next_actor"])
def test_hub_tools_explain_join_before_address(tool_name):
    text = _description(tool_name)
    assert "join_thread" in text, f"{tool_name} does not mention join_thread"
    assert "baton" in text.lower() or "to_participant" in text, tool_name


@pytest.mark.parametrize("tool_name", ["create_project", "get_context"])
def test_alias_pair_is_explained(tool_name):
    text = _description(tool_name)
    assert "taxonomy_alias" in text, tool_name
    assert "share code" in text.lower(), tool_name
    assert "BE-0007" in text, tool_name
