# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9035d -- ``_detected_harness`` live-first / persisted-fallback precedence (unit).

FINDING #4: ``FastMCP(stateless_http=True)`` drops the ``initialize`` clientInfo on
every non-``initialize`` tools/call, so the LIVE ``ctx.session.client_params`` read in
``_detected_harness`` always saw ``generic`` on the render path -- a claude-code CLI got
the ``<your-harness>`` generic ladder instead of the Claude-native spawn prose. The fix
adds a fallback to the harness PERSISTED at initialize time and stamped onto scope state
(``_persisted_harness``). These pure tests pin the precedence contract at the function
the bug lived in; the transport-boundary proof lives in the integration + api suites.

No DB, no transport -- fake ctx objects only. Edition Scope: Both.
"""

from __future__ import annotations

from types import SimpleNamespace

from api.endpoints.mcp_tools._base import _detected_harness, _persisted_harness


def _make_ctx(*, client_name: str | None, scope_state: dict | None):
    """Build a fake SDK ctx: a live clientInfo axis + a scope-state axis.

    ``client_name`` drives ``ctx.session.client_params.client_info`` (None -> the
    stateless-drop shape). ``scope_state`` is the ASGI ``scope['state']`` dict the
    middleware would have stamped (``None`` -> no HTTP request, the in-memory floor).
    """
    client_info = SimpleNamespace(name=client_name, version="9.9.9") if client_name is not None else None
    session = SimpleNamespace(client_params=SimpleNamespace(client_info=client_info))
    request = SimpleNamespace(scope={"state": scope_state}) if scope_state is not None else None
    return SimpleNamespace(session=session, request_context=SimpleNamespace(request=request))


class _RaisingSession:
    @property
    def client_params(self):  # noqa: D401 - simulate SDK attribute access blowing up
        raise RuntimeError("no live session on a stateless tools/call")


def test_live_concrete_harness_wins_and_ignores_persisted():
    """A live claude-code clientInfo wins outright -- the persisted value is never consulted."""
    ctx = _make_ctx(client_name="claude-code", scope_state={"resolved_harness": "codex"})
    assert _detected_harness(ctx) == "claude-code"


def test_live_generic_falls_back_to_persisted_claude_code():
    """The stateless drop (no live clientInfo) recovers the persisted claude-code token."""
    ctx = _make_ctx(client_name=None, scope_state={"resolved_harness": "claude-code"})
    assert _detected_harness(ctx) == "claude-code"


def test_live_generic_and_no_persisted_is_generic_floor():
    """No live clientInfo and nothing stamped -> the generic fail-safe floor (byte-identity)."""
    ctx = _make_ctx(client_name=None, scope_state={})
    assert _detected_harness(ctx) == "generic"


def test_no_http_request_is_generic_floor():
    """The in-memory transport (no request) cannot recover a persisted value -> generic."""
    ctx = _make_ctx(client_name=None, scope_state=None)
    assert _detected_harness(ctx) == "generic"


def test_live_read_raising_still_falls_back_to_persisted():
    """A live-read exception must never propagate; the persisted fallback still resolves."""
    ctx = SimpleNamespace(
        session=_RaisingSession(),
        request_context=SimpleNamespace(request=SimpleNamespace(scope={"state": {"resolved_harness": "gemini"}})),
    )
    assert _detected_harness(ctx) == "gemini"


def test_persisted_harness_reads_scope_state():
    """``_persisted_harness`` returns the stamped token, or None when absent/no-request."""
    ctx = _make_ctx(client_name=None, scope_state={"resolved_harness": "claude-code"})
    assert _persisted_harness(ctx) == "claude-code"

    assert _persisted_harness(_make_ctx(client_name=None, scope_state={})) is None
    assert _persisted_harness(_make_ctx(client_name=None, scope_state=None)) is None


def test_persisted_harness_never_raises_on_garbage_ctx():
    """A malformed ctx must degrade to None, never raise into the tool caller."""
    assert _persisted_harness(SimpleNamespace()) is None
