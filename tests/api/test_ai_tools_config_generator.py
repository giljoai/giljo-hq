# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Unit tests for AI Tools config-generator (api/endpoints/ai_tools.py).

Covers the Claude Desktop generator added for the AI Tool Config Wizard:
- self-signed HTTPS backend (self-signed/LAN, features.ssl_enabled=True) injects
  NODE_TLS_REJECT_UNAUTHORIZED="0"
- proxied HTTPS backend (TLS terminated upstream, features.ssl_enabled=False)
  omits NODE_TLS_REJECT_UNAUTHORIZED
- plain HTTP localhost omits NODE_TLS_REJECT_UNAUTHORIZED

These are pure-function tests; the FastAPI endpoint composes server_url
and the self-signed flag from request + state.config and forwards to the
generator under test.
"""

import json

from api.endpoints import ai_tools


SERVER_URL_HTTPS = "https://192.0.2.10:7272"
SERVER_URL_PROXIED = "https://giljo.example.com"
SERVER_URL_HTTP = "http://localhost:7272"
API_KEY = "test-api-key" + "-abc123"  # test fixture


def _parse(config_content: str) -> dict:
    return json.loads(config_content)


def test_claude_desktop_self_signed_https_injects_tls_bypass():
    """Self-signed HTTPS (self-signed/LAN) → NODE_TLS_REJECT_UNAUTHORIZED present."""
    raw = ai_tools.get_claude_desktop_config(
        SERVER_URL_HTTPS,
        API_KEY,
        self_signed_https=True,
    )
    cfg = _parse(raw)

    assert "mcpServers" in cfg
    assert "giljo_hq" in cfg["mcpServers"]
    entry = cfg["mcpServers"]["giljo_hq"]

    assert entry["command"] == "npx"
    assert entry["args"] == [
        "mcp-remote",
        f"{SERVER_URL_HTTPS}/mcp",
        "--header",
        "Authorization:${AUTH_HEADER}",
    ]
    assert entry["env"]["AUTH_HEADER"] == f"Bearer {API_KEY}"
    assert entry["env"]["NODE_TLS_REJECT_UNAUTHORIZED"] == "0"


def test_claude_desktop_proxied_https_omits_tls_bypass():
    """Proxied HTTPS (reverse-proxy TLS) → no NODE_TLS_REJECT_UNAUTHORIZED."""
    raw = ai_tools.get_claude_desktop_config(
        SERVER_URL_PROXIED,
        API_KEY,
        self_signed_https=False,
    )
    cfg = _parse(raw)

    entry = cfg["mcpServers"]["giljo_hq"]
    assert entry["args"][1] == f"{SERVER_URL_PROXIED}/mcp"
    assert entry["env"]["AUTH_HEADER"] == f"Bearer {API_KEY}"
    assert "NODE_TLS_REJECT_UNAUTHORIZED" not in entry["env"]


def test_claude_desktop_plain_http_omits_tls_bypass():
    """Plain HTTP localhost → no NODE_TLS_REJECT_UNAUTHORIZED."""
    raw = ai_tools.get_claude_desktop_config(
        SERVER_URL_HTTP,
        API_KEY,
        self_signed_https=False,
    )
    cfg = _parse(raw)

    entry = cfg["mcpServers"]["giljo_hq"]
    assert entry["args"][1] == f"{SERVER_URL_HTTP}/mcp"
    assert entry["env"]["AUTH_HEADER"] == f"Bearer {API_KEY}"
    assert "NODE_TLS_REJECT_UNAUTHORIZED" not in entry["env"]


def test_http_tool_instructions_claude_says_claude_code_cli():
    """Naming-update guard: user-facing 'claude' branch says 'Claude Code CLI'."""
    steps = ai_tools.get_http_tool_instructions("claude")
    joined = " ".join(steps)
    assert "Claude Code CLI" in joined
    assert "Claude Desktop" not in joined


def test_claude_desktop_registered_in_config_generators():
    """claude_desktop must be a sibling of claude/codex/gemini in the dict."""
    assert "claude_desktop" in ai_tools.CONFIG_GENERATORS
    entry = ai_tools.CONFIG_GENERATORS["claude_desktop"]
    assert entry["format"] == "json"
    assert entry["filename"].endswith(".md")
