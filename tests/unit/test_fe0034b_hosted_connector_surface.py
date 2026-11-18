# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.events.schemas import EventFactory
from giljo_mcp.harness_resolver import connector_surface_from_client_name


@pytest.mark.parametrize(
    ("client_name", "surface"),
    [
        ("Anthropic/ClaudeAI", "claude"),
        ("openai-mcp", "chatgpt"),
        ("openai-mcp (ChatGPT)", "chatgpt"),
        ("openai-mcp (Codex)", None),
        ("Anthropic/Toolbox", None),
        ("claude-code", None),
        ("", None),
        (None, None),
    ],
)
def test_connector_surface_from_client_name(client_name, surface):
    assert connector_surface_from_client_name(client_name) == surface


def test_event_carries_surface_when_given():
    event = EventFactory.setup_tool_connected(tenant_key="t", user_id="u", tool_name="generic", surface="chatgpt")
    assert event["data"]["surface"] == "chatgpt"


def test_event_surface_defaults_to_none_for_existing_callers():
    event = EventFactory.setup_tool_connected(tenant_key="t", user_id="u", tool_name="claude-code")
    assert event["data"]["surface"] is None
    assert event["data"]["tool_name"] == "claude-code"
