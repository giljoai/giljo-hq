# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9327 -- the preset-detection producer, its drift guard, and its survival path.

The MCP-boundary proof (a real ``openai-mcp`` initialize reaching ``giljo_setup``'s
inline branch) lives in
tests/integration/test_be9327_giljo_setup_inline_targeting_mcp_boundary.py. These
pure tests pin the three things that test cannot see:

  1. the exact targeting table, including what is deliberately NOT targeted;
  2. the DRIFT GUARD -- ``harness_resolver`` is the leaf module and cannot import
     ``platform_registry``, so its preset tokens are literals. Nothing but this
     assertion stops one from rotting into a token that resolves to no preset row
     and silently disables detection again;
  3. the stateless_http survival path: ``preset`` must be recoverable from the
     PERSISTED session row, because the tool that branches on it is always a
     tools/call and clientInfo is dropped on every one of those.

No DB, no transport -- fake ctx objects and pure functions only. Edition Scope: Both.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from api.endpoints.mcp_session import _client_info_patch
from api.endpoints.mcp_tools._harness import _detected_preset, _persisted_preset, get_session_capabilities
from api.endpoints.mcp_transport import _stamp_resolved_preset
from giljo_mcp.harness_resolver import _PRESET_BY_CLIENT_NAME, preset_from_client_info
from giljo_mcp.platform_registry import VALID_PRESETS, select_effective_preset


def _make_ctx(*, client_name: str | None, scope_state: dict | None):
    """Fake SDK ctx: a live clientInfo axis + an ASGI scope-state axis.

    ``client_name=None`` models the stateless_http drop (no live clientInfo);
    ``scope_state=None`` models the in-memory transport (no HTTP request at all).
    """
    client_info = SimpleNamespace(name=client_name, version="1.0.0") if client_name is not None else None
    session = SimpleNamespace(client_params=SimpleNamespace(client_info=client_info))
    session.check_client_capability = lambda cap: False
    request = SimpleNamespace(scope={"state": scope_state}) if scope_state is not None else None
    return SimpleNamespace(session=session, request_context=SimpleNamespace(request=request))


# ---------------------------------------------------------------------------
# 1. The targeting table
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("client_name", "expected"),
    [
        ("openai-mcp", "chat"),
        ("openai-mcp (ChatGPT)", "chat"),
        ("openai-mcp (Codex)", "web_sandbox"),
    ],
)
def test_hosted_openai_surfaces_resolve_a_preset(client_name, expected):
    """The openai-mcp family arrives as distinct unambiguous names, so it IS targetable."""
    assert preset_from_client_info(client_name) == expected


def test_anthropic_family_is_deliberately_untargeted():
    """Claude Desktop and claude.ai web send the IDENTICAL string.

    Auto-targeting it would either regress Desktop's working file install (map to
    chat) or gain claude.ai nothing (map to desktop_app). It stays declared-only.
    This is the recorded BE-9327 decision; the assertion is what keeps it recorded.
    """
    assert preset_from_client_info("Anthropic/ClaudeAI") is None


@pytest.mark.parametrize(
    "client_name",
    [
        None,
        "",
        "   ",
        "claude-code",  # a real terminal CLI keeps its filesystem path
        "codex-mcp-client",  # the NATIVE codex CLI, not the hosted connector
        "Anthropic/Toolbox",  # a connector-validation probe, not a user session
        "opencode-check",
        "openai-mcp-proxy",  # lookalike: matching is exact, never prefix/substring
        "OPENAI-MCP",  # lookalike: matching is case-sensitive
    ],
)
def test_everything_else_resolves_to_no_preset(client_name):
    """Conservative floor: anything not unambiguously hosted degrades to None.

    None means "no preset applies", which leaves the caller byte-identical to the
    pre-BE-9327 declared-only behaviour.
    """
    assert preset_from_client_info(client_name) is None


# ---------------------------------------------------------------------------
# 2. The drift guard
# ---------------------------------------------------------------------------


def test_every_targeted_preset_token_is_a_real_registry_preset():
    """The literals in the leaf module must name presets the registry can resolve.

    ``harness_resolver`` cannot import ``platform_registry`` (the dependency runs the
    other way), so its tokens are duplicated literals. A typo would make
    ``select_effective_preset`` return None for a correctly-detected client and
    silently restore the exact defect BE-9327 fixed -- with every other test still
    green. This is the mechanism that makes that impossible.
    """
    assert set(_PRESET_BY_CLIENT_NAME.values()) <= set(VALID_PRESETS), (
        f"unknown preset token(s): {set(_PRESET_BY_CLIENT_NAME.values()) - set(VALID_PRESETS)}"
    )


def test_detected_preset_actually_drives_select_effective_preset():
    """End-to-end on the pure layer: the produced key is the one the consumer reads."""
    caps = get_session_capabilities(_make_ctx(client_name="openai-mcp", scope_state={}))
    preset = select_effective_preset("", caps)

    assert preset is not None, "the capability vector must now resolve a preset"
    assert preset.execution_mode == "chat"


def test_declared_harness_still_beats_a_detected_preset():
    """Precedence is unchanged: an explicit declaration outranks detection."""
    caps = get_session_capabilities(_make_ctx(client_name="openai-mcp", scope_state={}))
    preset = select_effective_preset("desktop_app", caps)

    assert preset is not None
    assert preset.execution_mode == "desktop_app"


# ---------------------------------------------------------------------------
# 3. The capability vector + the stateless_http survival path
# ---------------------------------------------------------------------------


def test_capability_vector_always_carries_the_preset_key():
    """One fixed shape: the key is present as None rather than absent."""
    caps = get_session_capabilities(_make_ctx(client_name="claude-code", scope_state={}))

    assert "preset" in caps, "readers must not have to distinguish two vector shapes"
    assert caps["preset"] is None
    assert caps["harness"] == "claude-code", "the harness axis must be unaffected"


def test_live_clientinfo_wins_over_a_stamped_preset():
    ctx = _make_ctx(client_name="openai-mcp (Codex)", scope_state={"resolved_preset": "chat"})
    assert _detected_preset(ctx) == "web_sandbox"


def test_stateless_drop_recovers_the_persisted_preset():
    """THE SURVIVAL PATH: no live clientInfo (every tools/call) still resolves."""
    ctx = _make_ctx(client_name=None, scope_state={"resolved_preset": "chat"})
    assert _detected_preset(ctx) == "chat"


def test_no_live_and_nothing_stamped_is_none():
    assert _detected_preset(_make_ctx(client_name=None, scope_state={})) is None
    assert _detected_preset(_make_ctx(client_name=None, scope_state=None)) is None


def test_detection_never_raises_into_the_tool():
    """A malformed ctx degrades to None; detection is a render hint, never a gate."""

    class _RaisingSession:
        @property
        def client_params(self):
            raise RuntimeError("no live session on a stateless tools/call")

    ctx = SimpleNamespace(
        session=_RaisingSession(),
        request_context=SimpleNamespace(request=SimpleNamespace(scope={"state": {"resolved_preset": "chat"}})),
    )
    assert _detected_preset(ctx) == "chat"
    assert _persisted_preset(SimpleNamespace()) is None


def test_initialize_capture_persists_the_preset():
    """The session row written at initialize carries the token the stamp later reads."""
    patch = _client_info_patch({"name": "openai-mcp", "version": "1.0.0"})

    assert patch["resolved_preset"] == "chat"
    assert patch["resolved_harness"] == "generic", "the harness axis is unchanged"

    cli_patch = _client_info_patch({"name": "claude-code", "version": "2.1.199"})
    assert cli_patch["resolved_preset"] is None


def test_stamp_surfaces_the_persisted_preset_onto_scope_state():
    scope: dict = {}
    _stamp_resolved_preset(scope, SimpleNamespace(session_data={"resolved_preset": "web_sandbox"}))
    assert scope["state"]["resolved_preset"] == "web_sandbox"


@pytest.mark.parametrize(
    "session_data",
    [
        {"client_info": {}, "resolved_harness": "generic"},  # a row written BEFORE BE-9327
        {"resolved_preset": None},
        {"resolved_preset": ""},
        None,
    ],
)
def test_stamp_leaves_state_untouched_when_no_preset_applies(session_data):
    """Legacy rows lack the key entirely; they must resolve exactly as they do today."""
    scope: dict = {}
    _stamp_resolved_preset(scope, SimpleNamespace(session_data=session_data))
    assert "resolved_preset" not in scope.get("state", {})
