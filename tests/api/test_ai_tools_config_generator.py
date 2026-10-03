# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import json

from api.endpoints import ai_tools


SERVER_URL_HTTPS = "https://192.0.2.10:7272"
SERVER_URL_PROXIED = "https://giljo.example.com"
SERVER_URL_HTTP = "http://localhost:7272"
API_KEY = "test-api-key" + "-abc123"


def _parse(config_content: str) -> dict:
    return json.loads(config_content)


def test_claude_desktop_config_never_touches_tls_verification():
    for server_url in (SERVER_URL_HTTPS, SERVER_URL_PROXIED, SERVER_URL_HTTP):
        entry = _parse(ai_tools.get_claude_desktop_config(server_url, API_KEY))["mcpServers"]["giljo_hq"]

        assert entry["command"] == "npx"
        assert entry["args"] == [
            "mcp-remote",
            f"{server_url}/mcp",
            "--header",
            "Authorization:${AUTH_HEADER}",
        ]
        assert entry["env"] == {"AUTH_HEADER": f"Bearer {API_KEY}"}


def test_http_tool_instructions_claude_says_claude_code_cli():
    steps = ai_tools.get_http_tool_instructions("claude")
    joined = " ".join(steps)
    assert "Claude Code CLI" in joined
    assert "Claude Desktop" not in joined


def test_claude_desktop_registered_in_config_generators():
    assert "claude_desktop" in ai_tools.CONFIG_GENERATORS
    entry = ai_tools.CONFIG_GENERATORS["claude_desktop"]
    assert entry["format"] == "json"
    assert entry["filename"].endswith(".md")
