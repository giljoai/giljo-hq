# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

from api.endpoints.mcp_tools._base import _detected_harness, _persisted_harness


def _make_ctx(*, client_name: str | None, scope_state: dict | None):
    client_info = SimpleNamespace(name=client_name, version="9.9.9") if client_name is not None else None
    session = SimpleNamespace(client_params=SimpleNamespace(client_info=client_info))
    request = SimpleNamespace(scope={"state": scope_state}) if scope_state is not None else None
    return SimpleNamespace(session=session, request_context=SimpleNamespace(request=request))


class _RaisingSession:
    @property
    def client_params(self):  # noqa: D401 - simulate SDK attribute access blowing up
        raise RuntimeError("no live session on a stateless tools/call")


def test_live_concrete_harness_wins_and_ignores_persisted():
    ctx = _make_ctx(client_name="claude-code", scope_state={"resolved_harness": "codex"})
    assert _detected_harness(ctx) == "claude-code"


def test_live_generic_falls_back_to_persisted_claude_code():
    ctx = _make_ctx(client_name=None, scope_state={"resolved_harness": "claude-code"})
    assert _detected_harness(ctx) == "claude-code"


def test_live_generic_and_no_persisted_is_generic_floor():
    ctx = _make_ctx(client_name=None, scope_state={})
    assert _detected_harness(ctx) == "generic"


def test_no_http_request_is_generic_floor():
    ctx = _make_ctx(client_name=None, scope_state=None)
    assert _detected_harness(ctx) == "generic"


def test_live_read_raising_still_falls_back_to_persisted():
    ctx = SimpleNamespace(
        session=_RaisingSession(),
        request_context=SimpleNamespace(request=SimpleNamespace(scope={"state": {"resolved_harness": "gemini"}})),
    )
    assert _detected_harness(ctx) == "gemini"


def test_persisted_harness_reads_scope_state():
    ctx = _make_ctx(client_name=None, scope_state={"resolved_harness": "claude-code"})
    assert _persisted_harness(ctx) == "claude-code"

    assert _persisted_harness(_make_ctx(client_name=None, scope_state={})) is None
    assert _persisted_harness(_make_ctx(client_name=None, scope_state=None)) is None


def test_persisted_harness_never_raises_on_garbage_ctx():
    assert _persisted_harness(SimpleNamespace()) is None
