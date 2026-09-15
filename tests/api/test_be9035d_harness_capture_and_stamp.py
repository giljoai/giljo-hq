# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


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




async def test_initialize_persists_resolved_harness_for_claude_code(db_manager, jwt_env):
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




async def test_tools_call_stamps_claude_code_onto_scope_state(db_manager, jwt_env):
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




async def test_initialize_persists_resolved_preset_for_hosted_chat_client(db_manager, jwt_env):
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
