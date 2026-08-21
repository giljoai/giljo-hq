# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8003g — giljo_setup's no-filesystem inline mode, proven LIVE at the MCP
transport (CLAUDE.md failing-layer mandate: a service-layer test would not
catch a wrapper-boundary regression, per BE-5042).

``giljo_setup`` is the harness param's second wrapper (after BE-8003f/f2's
``get_staging_instructions`` / ``get_job_mission``): a session whose resolved
harness preset has no real home directory (``web_sandbox`` / ``chat``) gets an
INLINE response (agent template content in-band, no filesystem-write
instructions) instead of ``bootstrap_setup``'s ZIP-download install prompt.
``desktop_app`` (a real home dir, same as every CLI) and the default
``harness=""`` stay on the unchanged byte-identical install-instruction path.

Parallel-safe: no module-level mutable state, no DB (stub ToolAccessor mirrors
tests/integration/test_imp6038_giljo_setup_ack_mcp_boundary.py and
tests/integration/test_be6041b_antigravity_cli.py). Edition Scope: Both.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

# Literal OS-write instructions the inline branch must NEVER emit (DoD item 4).
_OS_WRITE_MARKERS = ("~/.claude", "~/.codex", "~/.gemini", "python3 -c", "agy plugin")


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    return "\n".join(b.text for b in call_tool_result.content if getattr(b, "text", None))


@pytest_asyncio.fixture
async def giljo_setup_client(monkeypatch, db_manager):
    """In-memory FastMCP client wired for giljo_setup harness-branch tests.

    Mirrors test_imp6038_giljo_setup_ack_mcp_boundary.giljo_setup_client / the
    test_be6041b_antigravity_cli fixture: stub bootstrap_setup + a fake
    list_agent_templates (so the inline branch has assembled content to strip
    install_paths from and assert against, without seeding real AgentTemplate
    rows), wire the test db_manager, scope the tenant, neutralise post-call
    side effects.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    class _StubAccessor:
        # BE-9385b: giljo_setup forwards the resolved harness so the install
        # prose can target the repository. **_kwargs rather than a named
        # parameter so this stub stops breaking every time the real
        # accessor gains an argument it does not care about.
        async def bootstrap_setup(self, platform: str, user_id=None, **_kwargs):
            return {
                "status": "ready",
                "platform": platform,
                "next_action": {"why": "Download the zip and extract agents/* into ~/.claude/agents/."},
            }

        async def list_agent_templates(self, platform: str):
            return {
                "platform": platform,
                "agents": [{"filename": "implementer.md", "content": "# Implementer\nDo the thing."}],
                "install_paths": {"project": ".claude/agents/", "user": "~/.claude/agents/"},
                "template_count": 1,
                "format_version": "1.0",
            }

    state.tool_accessor = _StubAccessor()

    tenant_key = TenantManager.generate_tenant_key()
    from api.endpoints.mcp_tools import _base

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    async def _noop(*args, **kwargs):
        return None

    monkeypatch.setattr("giljo_mcp.services.silence_detector.auto_clear_silent", _noop)
    monkeypatch.setattr("giljo_mcp.services.heartbeat.touch_heartbeat", _noop)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


@pytest.mark.parametrize("harness", ["web_sandbox", "chat"])
async def test_giljo_setup_no_filesystem_harness_returns_inline_mode(giljo_setup_client, harness):
    """A no-home-dir harness gets inline template content, zero OS-write instructions."""
    new_client, _tenant_key = giljo_setup_client

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "harness": harness})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert payload["mode"] == "inline"
    assert "install_paths" not in payload, "inline mode must not carry filesystem install paths"
    assert payload["agents"][0]["content"] == "# Implementer\nDo the thing.", "inline template content must survive"

    # BE-9067: the no-home-dir path still teaches the platform mental model, via the
    # memory-system fallback rather than a startup file it cannot write.
    from giljo_mcp.tools.setup_instructions import GILJOAI_MCP_PRIMER

    assert GILJOAI_MCP_PRIMER in payload["primer"], f"inline mode ({harness}) missing the GiljoAI primer"
    assert "code-memory system" in payload["primer"]

    blob = json.dumps(payload)
    for marker in _OS_WRITE_MARKERS:
        assert marker not in blob, f"inline mode ({harness}) leaked OS-write instruction {marker!r}"


async def test_giljo_setup_desktop_app_harness_keeps_filesystem_path(giljo_setup_client):
    """desktop_app HAS a real home dir (shared_working_tree) -- normal install path stays."""
    new_client, _tenant_key = giljo_setup_client

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "harness": "desktop_app"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, "desktop_app must reach bootstrap_setup, not the inline branch"
    assert "~/.claude/agents/" in payload["next_action"]["why"]


@pytest.mark.parametrize("harness", ["", "not_a_real_harness"])
async def test_giljo_setup_default_and_garbage_harness_degrade_to_cli_path(giljo_setup_client, harness):
    """harness='' (every existing caller) AND a garbage token degrade to None -> the
    unchanged bootstrap_setup install-instruction path (byte-identity floor)."""
    new_client, _tenant_key = giljo_setup_client

    async with new_client() as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "harness": harness})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, f"harness={harness!r} must NOT reach the inline branch"
    assert "~/.claude/agents/" in payload["next_action"]["why"]
