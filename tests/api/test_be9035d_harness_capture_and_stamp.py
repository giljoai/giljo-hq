# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9035d -- harness CAPTURE at initialize + STAMP onto scope state, at the real transport.

The render fallback (``_detected_harness`` -> ``_persisted_harness``) is only useful if two
transport-layer halves actually work in the real stateless-HTTP path:

  (2) CAPTURE -- a fresh claude-code ``initialize`` persists ``resolved_harness='claude-code'``
      into ``MCPSession.session_data`` (load-bearing: DB evidence had shown a claude-code row
      reading 'generic', so this proves the real streamable-HTTP connect stamps correctly),
      and a subsequent no-clientInfo tools/call PRESERVES it.
  (1a) STAMP -- on a non-initialize tools/call ``_stamp_resolved_harness`` surfaces the
      persisted token onto ``scope['state']['resolved_harness']`` so the tool render can read
      it after ``stateless_http`` has dropped the live ``client_params``.

Both are exercised end-to-end by driving real JSON-RPC payloads through ``MCPAuthMiddleware``
(the same boundary a real MCP client hits) -- NOT a unit test of an inner helper. Reuses the
seed + middleware drivers from ``tests/api/test_mcp_session.py``. Edition Scope: Both.
"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from tests.api.test_mcp_session import (  # noqa: E402
    _drive_middleware_with_body,
    _jsonrpc_body,
    _seed_api_key,
)


pytestmark = pytest.mark.asyncio


@pytest.fixture
def jwt_env(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test_secret_key")
    return "test_secret_key"


async def _read_session_data(db_manager, tenant_key: str, session_id: str) -> dict:
    from giljo_mcp.models import MCPSession

    async with db_manager.get_session_async() as db:
        with tenant_session_context(db, tenant_key):
            row = (await db.execute(select(MCPSession).where(MCPSession.session_id == session_id))).scalar_one()
            return row.session_data


class _StateCapturingApp:
    """Inner ASGI app that records what the middleware stamped onto ``scope['state']``."""

    def __init__(self) -> None:
        self.called = False
        self.resolved_harness_seen: object = "SENTINEL_UNSET"
        self.resolved_preset_seen: object = "SENTINEL_UNSET"

    async def __call__(self, scope, receive, send) -> None:
        self.called = True
        self.resolved_harness_seen = scope.get("state", {}).get("resolved_harness", "SENTINEL_UNSET")
        self.resolved_preset_seen = scope.get("state", {}).get("resolved_preset", "SENTINEL_UNSET")
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})


def _initialize_body(name: str, version: str = "9.9.9") -> bytes:
    return _jsonrpc_body(
        "initialize",
        params={"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": name, "version": version}},
    )


async def _initialize(db_manager, raw_key: str, name: str) -> str:
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    _status, headers, _body = await _drive_middleware_with_body(
        MCPAuthMiddleware(app=_StateCapturingApp()),
        headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
        body=_initialize_body(name),
    )
    session_id = headers.get("mcp-session-id")
    assert session_id, "initialize must issue an Mcp-Session-Id"
    return session_id


async def _tools_call(db_manager, raw_key: str, session_id: str) -> _StateCapturingApp:
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    inner = _StateCapturingApp()
    status, _headers, _body = await _drive_middleware_with_body(
        MCPAuthMiddleware(app=inner),
        headers=[
            (b"x-api-key", raw_key.encode()),
            (b"mcp-protocol-version", b"2025-06-18"),
            (b"mcp-session-id", session_id.encode("ascii")),
            (b"content-type", b"application/json"),
        ],
        body=_jsonrpc_body("tools/list"),
    )
    assert status == 200, f"tools/list on a valid session returned {status}"
    return inner


# ---------------------------------------------------------------------------
# (2) CAPTURE — the real initialize persists resolved_harness
# ---------------------------------------------------------------------------


async def test_initialize_persists_resolved_harness_for_claude_code(db_manager, jwt_env):
    """A fresh claude-code initialize stamps session_data['resolved_harness']='claude-code'."""
    from api.app_state import state

    raw_key, tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "claude-code")
        session_data = await _read_session_data(db_manager, tenant_key, session_id)
        assert session_data.get("resolved_harness") == "claude-code"
    finally:
        state.db_manager = prior_db


async def test_unrecognized_client_persists_generic(db_manager, jwt_env):
    """An unrecognized clientInfo name resolves to the generic floor (never a guessed token)."""
    from api.app_state import state

    raw_key, tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "totally-made-up-harness")
        session_data = await _read_session_data(db_manager, tenant_key, session_id)
        assert session_data.get("resolved_harness") == "generic"
    finally:
        state.db_manager = prior_db


async def test_tools_call_preserves_persisted_resolved_harness(db_manager, jwt_env):
    """A no-clientInfo tools/call after a claude-code initialize preserves the stamped token."""
    from api.app_state import state

    raw_key, tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "claude-code")
        await _tools_call(db_manager, raw_key, session_id)
        session_data = await _read_session_data(db_manager, tenant_key, session_id)
        assert session_data.get("resolved_harness") == "claude-code", "reuse must not drop the captured harness"
    finally:
        state.db_manager = prior_db


# ---------------------------------------------------------------------------
# (1a) STAMP — the tools/call surfaces the persisted harness onto scope state
# ---------------------------------------------------------------------------


async def test_tools_call_stamps_claude_code_onto_scope_state(db_manager, jwt_env):
    """The stateless-drop recovery vehicle: a non-initialize tools/call stamps the persisted
    claude-code token onto scope['state']['resolved_harness'] for the tool render to read."""
    from api.app_state import state

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "claude-code")
        inner = await _tools_call(db_manager, raw_key, session_id)
        assert inner.called is True
        assert inner.resolved_harness_seen == "claude-code", (
            "the persisted harness must be stamped onto scope state on the tools/call"
        )
    finally:
        state.db_manager = prior_db


async def test_tools_call_does_not_stamp_generic(db_manager, jwt_env):
    """A generic session leaves scope state UNSTAMPED so the declared CLI hint still governs
    (only a concrete detected harness is surfaced)."""
    from api.app_state import state

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "totally-made-up-harness")
        inner = await _tools_call(db_manager, raw_key, session_id)
        assert inner.called is True
        assert inner.resolved_harness_seen == "SENTINEL_UNSET", "a generic harness must not be stamped"
    finally:
        state.db_manager = prior_db


# ---------------------------------------------------------------------------
# BE-9327 — the PRESET axis rides the same two halves, and must be proven on the
# same real-transport seam. The unit tests cover the capture function and the
# stamp function in isolation; only this proves the middleware actually CALLS the
# stamp, which is precisely the "green units, dead seam" gap that left the preset
# key unproduced for the whole of BE-8003g's life.
# ---------------------------------------------------------------------------


async def test_initialize_persists_resolved_preset_for_hosted_chat_client(db_manager, jwt_env):
    """A real openai-mcp initialize persists session_data['resolved_preset']='chat'."""
    from api.app_state import state

    raw_key, tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "openai-mcp")
        session_data = await _read_session_data(db_manager, tenant_key, session_id)
        assert session_data.get("resolved_preset") == "chat"
        assert session_data.get("resolved_harness") == "generic", "the harness axis is unchanged"
    finally:
        state.db_manager = prior_db


async def test_tools_call_stamps_resolved_preset_onto_scope_state(db_manager, jwt_env):
    """THE SEAM: a non-initialize tools/call surfaces the persisted preset onto scope state.

    ``giljo_setup`` is always a tools/call, and ``stateless_http`` has dropped the
    live clientInfo by then, so this stamp is the ONLY way the inline branch can see
    that the session has no filesystem.
    """
    from api.app_state import state

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "openai-mcp")
        inner = await _tools_call(db_manager, raw_key, session_id)
        assert inner.called is True
        assert inner.resolved_preset_seen == "chat", (
            "the persisted preset must be stamped onto scope state on the tools/call"
        )
    finally:
        state.db_manager = prior_db


async def test_tools_call_does_not_stamp_a_preset_for_a_terminal_cli(db_manager, jwt_env):
    """A claude-code session has a real home directory — nothing to stamp, nothing changes."""
    from api.app_state import state

    raw_key, _tenant_key = await _seed_api_key(db_manager)
    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        session_id = await _initialize(db_manager, raw_key, "claude-code")
        inner = await _tools_call(db_manager, raw_key, session_id)
        assert inner.called is True
        assert inner.resolved_preset_seen == "SENTINEL_UNSET", "a terminal CLI must not be given a preset"
    finally:
        state.db_manager = prior_db
