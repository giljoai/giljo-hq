# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest

from giljo_mcp.harness_resolver import connector_surface_from_oauth_client_id


_CLAUDE_AI_CLIENT = "https://claude.ai/oauth/mcp-oauth-client-metadata"


@pytest.mark.parametrize(
    ("client_id", "mcp_name", "expected"),
    [
        (_CLAUDE_AI_CLIENT, None, "claude"),
        (_CLAUDE_AI_CLIENT, "Anthropic/ClaudeAI", "claude"),
        (_CLAUDE_AI_CLIENT, "claude-code", None),
        ("https://claude.ai/oauth/claude-code-client-metadata", None, None),
        ("https://chatgpt.com/oauth/client.json", None, "chatgpt"),
        ("https://chatgpt.com/oauth/abc123/client.json", None, "chatgpt"),
        ("https://chatgpt.com/oauth/codex/client.json", None, None),
        ("https://chatgpt.com.evil.example/oauth/client.json", None, None),
        ("https://cursor.com/oauth/mcp-client.json", None, None),
        ("giljo-mcp-default", None, None),
        (None, None, None),
    ],
)
def test_surface_from_client_id(client_id, mcp_name, expected):
    assert connector_surface_from_oauth_client_id(client_id, mcp_name) == expected
