# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9327 -- the shell-less-harness preset key, proven LIVE at the MCP transport.

BE-8003g shipped ``giljo_setup``'s INLINE branch for sessions with no home
directory, but nothing ever selected it by DETECTION: the branch resolves its
preset through ``select_effective_preset``, which reads ``capabilities["preset"]``
(platform_registry), and no producer ever wrote that key --
``get_session_capabilities`` returned only ``{elicitation, tasks, harness}``. A
ChatGPT connector session therefore received filesystem install instructions for
directories it cannot write to: no error, just steps that silently cannot be
followed.

This drives the REAL FastMCP transport with a genuine ``initialize`` clientInfo,
the way a hosted connector does, because the defect lives at the @mcp.tool
wrapper boundary (CLAUDE.md failing-layer mandate / BE-5042): a service-layer
test cannot see a capability vector that is assembled in the wrapper.

Targeting posture asserted here (BE-9327 product decision, recorded in
``harness_resolver._PRESET_BY_CLIENT_NAME``): the ``openai-mcp*`` family is
auto-targeted because it arrives as distinct unambiguous names; the Anthropic
family is NOT, because Claude Desktop (a real home directory) and claude.ai web
(none) send the byte-identical string ``Anthropic/ClaudeAI`` -- auto-targeting it
would regress Desktop's working file install.

Parallel-safe: no DB, no module-level mutable state (stub ToolAccessor mirrors
tests/integration/test_be8003g_giljo_setup_inline_mode_mcp_boundary.py).
Edition Scope: Both.
"""

from __future__ import annotations

import json

import pytest
import pytest_asyncio
from mcp.types import Implementation

from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


# The three unambiguous OpenAI-hosted connector identifiers (harness_resolver's
# _KNOWN_GENERIC_CLIENT_NAMES rows) and the ambiguous Anthropic one.
_CHATGPT_INFO = Implementation(name="openai-mcp", version="1.0.0")
_CHATGPT_VALIDATION_INFO = Implementation(name="openai-mcp (ChatGPT)", version="1.0.0")
_CODEX_HOSTED_INFO = Implementation(name="openai-mcp (Codex)", version="1.0.0")
_ANTHROPIC_INFO = Implementation(name="Anthropic/ClaudeAI", version="1.0.0")
_CLAUDE_CODE_INFO = Implementation(name="claude-code", version="2.1.199")


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))


@pytest_asyncio.fixture
async def setup_client(monkeypatch, db_manager):
    """In-memory FastMCP client whose stub accessor RECORDS the platform it was asked for.

    The recording is the point: the renderer-default half of BE-9327 is invisible
    unless the test can see which platform ``giljo_setup`` forwarded to
    ``list_agent_templates``. The stub's agent rows carry a ``filename`` key
    exactly as the real generic assembler does, so the inline branch's strip is
    observable too.
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

    requested: dict[str, str] = {}

    class _StubAccessor:
        # BE-9385b: giljo_setup forwards the resolved harness so the install
        # prose can target the repository. **_kwargs rather than a named
        # parameter so this stub stops breaking every time the real
        # accessor gains an argument it does not care about.
        async def bootstrap_setup(self, platform: str, user_id=None, **_kwargs):
            requested["bootstrap_platform"] = platform
            return {
                "status": "ready",
                "platform": platform,
                "next_action": {"why": "Download the zip and extract agents/* into ~/.claude/agents/."},
            }

        async def list_agent_templates(self, platform: str):
            requested["templates_platform"] = platform
            return {
                "platform": platform,
                "agents": [
                    {
                        "filename": "implementer.md",
                        "content": "# Implementer\nDo the thing.",
                        "role": "implementer",
                    }
                ],
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

    def _client(client_info):
        return create_connected_server_and_client_session(mcp_sdk_server.mcp, client_info=client_info)

    try:
        yield _client, requested
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


@pytest.mark.parametrize(
    "client_info",
    [_CHATGPT_INFO, _CHATGPT_VALIDATION_INFO, _CODEX_HOSTED_INFO],
    ids=["chatgpt", "chatgpt-validation", "codex-hosted"],
)
async def test_openai_hosted_session_gets_inline_setup_without_declaring_a_harness(setup_client, client_info):
    """THE DEFECT: an openai-mcp initialize must select the inline branch by DETECTION.

    The client declares NO harness -- exactly what a hosted connector does. Before
    BE-9327 the capability vector carried no ``preset`` key, so the preset resolved
    to None and the call fell through to the filesystem-install branch.
    """
    new_client, _requested = setup_client

    async with new_client(client_info) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert payload.get("mode") == "inline", (
        f"{client_info.name} has no writable home directory but did NOT get inline setup; "
        f"payload keys={sorted(payload)}"
    )
    assert "install_paths" not in payload, "inline mode must not carry filesystem install paths"


async def test_inline_setup_renders_platform_neutral_templates(setup_client):
    """DoD 3: a client that cannot write files gets neutral markdown, not Claude Code files.

    ``platform`` defaults to ``claude_code`` on the wrapper and was forwarded
    unchanged into the inline branch, so a chat client asking for inline templates
    received YAML frontmatter and a ``filename`` for a file it cannot create.
    """
    new_client, requested = setup_client

    async with new_client(_CHATGPT_INFO) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert requested.get("templates_platform") == "generic", (
        "the inline branch must request the platform-neutral renderer, not the caller's "
        f"file-install platform (got {requested.get('templates_platform')!r})"
    )
    assert payload["agents"], "inline mode must still return template content"
    for agent in payload["agents"]:
        assert "filename" not in agent, "a session with no filesystem must not be handed a filename"
        assert agent["content"], "inline template content must survive"


async def test_anthropic_family_is_not_auto_targeted(setup_client):
    """Claude Desktop and claude.ai web send the IDENTICAL name -- auto-targeting regresses Desktop.

    So ``Anthropic/ClaudeAI`` stays on the declared-only path: the file-install
    branch, byte-identical to today. This is the recorded BE-9327 decision, pinned
    as a test so a future "just map it too" cannot land silently.
    """
    new_client, _requested = setup_client

    async with new_client(_ANTHROPIC_INFO) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, "Anthropic/ClaudeAI must NOT be auto-targeted to the inline branch"
    assert "~/.claude/agents/" in payload["next_action"]["why"]


async def test_terminal_cli_session_is_unaffected(setup_client):
    """Byte-identity floor: a real CLI keeps the filesystem install path it has today."""
    new_client, requested = setup_client

    async with new_client(_CLAUDE_CODE_INFO) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, "a terminal CLI must reach bootstrap_setup, not the inline branch"
    assert requested.get("bootstrap_platform") == "claude_code"


async def test_declared_desktop_app_harness_still_keeps_filesystem_path(setup_client):
    """DoD 2 regression guard: desktop_app HAS a real home dir even from a hosted client."""
    new_client, _requested = setup_client

    async with new_client(_CHATGPT_INFO) as session:
        result = await session.call_tool("giljo_setup", {"platform": "claude_code", "harness": "desktop_app"})

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert "mode" not in payload, "declared desktop_app must beat the detected preset"
    assert "~/.claude/agents/" in payload["next_action"]["why"]


# ---------------------------------------------------------------------------
# AUDIT-9327 F1 — the ``filename`` strip is keyed on WORKSPACE_NONE, not on the
# inline branch as a whole. Both presets reach the inline branch, but they differ
# in the one way the strip cares about: ``chat`` has no filesystem
# (WORKSPACE_NONE), while ``web_sandbox`` has an isolated PR checkout
# (WORKSPACE_ISOLATED_PR) it CAN write to. Stripping the suggested name from a
# session that can act on it costs ergonomics for no benefit -- and the DoD's own
# wording scopes the strip to "a client that cannot write files".
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("client_info", "declared_harness", "expect_filename"),
    [
        # web_sandbox CAN write files -> keeps the suggested filename.
        (_CODEX_HOSTED_INFO, "", True),  # reached by DETECTION (hosted Codex)
        (_CHATGPT_INFO, "web_sandbox", True),  # reached by DECLARATION (predates BE-9327)
        # chat has no filesystem at all -> must not be handed a name it cannot use.
        (_CHATGPT_INFO, "", False),  # reached by DETECTION (ChatGPT)
        (_CLAUDE_CODE_INFO, "chat", False),  # reached by DECLARATION
    ],
    ids=["web_sandbox-detected", "web_sandbox-declared", "chat-detected", "chat-declared"],
)
async def test_filename_is_stripped_only_when_the_session_has_no_filesystem(
    setup_client, client_info, declared_harness, expect_filename
):
    """Both sides pinned: web_sandbox KEEPS filename, a cannot-write client does NOT."""
    new_client, _requested = setup_client

    args: dict = {"platform": "claude_code"}
    if declared_harness:
        args["harness"] = declared_harness

    async with new_client(client_info) as session:
        result = await session.call_tool("giljo_setup", args)

    assert result.is_error is False, _error_text(result)
    payload = _payload(result)

    assert payload.get("mode") == "inline", "both presets must still take the inline branch"
    assert payload["agents"], "inline mode must still return template content"
    for agent in payload["agents"]:
        assert agent["content"], "inline template content must survive either way"
        if expect_filename:
            assert "filename" in agent, (
                "web_sandbox has an isolated PR workspace it CAN write to, so the suggested "
                "filename must survive the inline branch"
            )
        else:
            assert "filename" not in agent, "a session with no filesystem must not be handed a filename"
