# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9275a — two-hub disambiguation sentence coverage.

The 12 messaging/task tools (create_thread, post_to_thread, pass_baton,
get_my_turn, list_threads, get_thread_history, search_threads, join_thread,
create_task, update_task, list_tasks, health_check) must each carry the same
`branding.TWO_HUB_DISAMBIGUATION` sentence in their registered `@mcp.tool`
description, so an agent that also has Giljo AMH (giljo_amh) connected in the
same session asks the user which hub before posting.
"""

from api.endpoints.mcp_tools._base import mcp
from giljo_mcp import branding


_TWELVE_TOOLS = [
    "create_thread",
    "post_to_thread",
    "pass_baton",
    "get_my_turn",
    "list_threads",
    "get_thread_history",
    "search_threads",
    "join_thread",
    "create_task",
    "update_task",
    "list_tasks",
    "health_check",
]


def _registered_tools_by_name() -> dict:
    return {tool.name: tool for tool in mcp._tool_manager.list_tools()}


def test_all_twelve_tools_carry_the_disambiguation_sentence():
    tools = _registered_tools_by_name()
    missing_tool = [name for name in _TWELVE_TOOLS if name not in tools]
    assert not missing_tool, f"expected tools missing from registry: {missing_tool}"

    missing_sentence = [
        name for name in _TWELVE_TOOLS if branding.TWO_HUB_DISAMBIGUATION not in (tools[name].description or "")
    ]
    assert not missing_sentence, f"tools missing the two-hub disambiguation sentence: {missing_sentence}"
