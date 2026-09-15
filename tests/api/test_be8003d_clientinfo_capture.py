# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from giljo_mcp.database import tenant_session_context
from tests.api.test_mcp_session import (  # noqa: E402
    _drive_middleware_with_body,
    _jsonrpc_body,
    _seed_api_key,
)


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


@pytest.mark.asyncio
async def test_initialize_populates_client_info_on_new_session(db_manager, jwt_env):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, tenant_key = await _seed_api_key(db_manager)

    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        status, headers, _body = await _drive_middleware_with_body(
            MCPAuthMiddleware(app=_CapturingProbe()),
            headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
            body=_jsonrpc_body(
                "initialize",
                params={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-harness", "version": "9.9.9"},
                },
            ),
        )
        assert status == 200, f"initialize returned {status}"
        session_id = headers.get("mcp-session-id")
        assert session_id, "initialize must issue Mcp-Session-Id"

        session_data = await _read_session_data(db_manager, tenant_key, session_id)
        assert session_data.get("client_info") == {"name": "test-harness", "version": "9.9.9"}
    finally:
        state.db_manager = prior_db


@pytest.mark.asyncio
async def test_second_initialize_mints_new_session_and_preserves_first(db_manager, jwt_env):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, tenant_key = await _seed_api_key(db_manager)

    def _initialize(name: str, version: str):
        return _drive_middleware_with_body(
            MCPAuthMiddleware(app=_CapturingProbe()),
            headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
            body=_jsonrpc_body(
                "initialize",
                params={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": name, "version": version},
                },
            ),
        )

    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        _status, headers1, _body = await _initialize("first-client", "1.0.0")
        session_id_1 = headers1.get("mcp-session-id")
        assert session_id_1

        _status, headers2, _body = await _initialize("second-client", "2.0.0")
        session_id_2 = headers2.get("mcp-session-id")
        assert session_id_2 and session_id_2 != session_id_1, (
            "each initialize must mint its own session (per-connection, BE-9066)"
        )

        session_data_1 = await _read_session_data(db_manager, tenant_key, session_id_1)
        assert session_data_1.get("client_info") == {"name": "first-client", "version": "1.0.0"}, (
            "the second client's initialize must not overwrite the first session's clientInfo"
        )
        session_data_2 = await _read_session_data(db_manager, tenant_key, session_id_2)
        assert session_data_2.get("client_info") == {"name": "second-client", "version": "2.0.0"}
    finally:
        state.db_manager = prior_db


@pytest.mark.asyncio
async def test_non_initialize_call_does_not_touch_client_info(db_manager, jwt_env):
    from api.app_state import state
    from api.endpoints.mcp_sdk_server import MCPAuthMiddleware

    raw_key, tenant_key = await _seed_api_key(db_manager)

    prior_db = state.db_manager
    state.db_manager = db_manager
    try:
        _status, headers, _body = await _drive_middleware_with_body(
            MCPAuthMiddleware(app=_CapturingProbe()),
            headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
            body=_jsonrpc_body(
                "initialize",
                params={
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "test-harness", "version": "1.2.3"},
                },
            ),
        )
        session_id = headers.get("mcp-session-id")
        assert session_id

        status, _h, _b = await _drive_middleware_with_body(
            MCPAuthMiddleware(app=_CapturingProbe()),
            headers=[
                (b"x-api-key", raw_key.encode()),
                (b"mcp-session-id", session_id.encode("ascii")),
                (b"content-type", b"application/json"),
            ],
            body=_jsonrpc_body("tools/list"),
        )
        assert status == 200

        session_data = await _read_session_data(db_manager, tenant_key, session_id)
        assert session_data.get("client_info") == {"name": "test-harness", "version": "1.2.3"}
    finally:
        state.db_manager = prior_db


class _CapturingProbe:

    async def __call__(self, scope, receive, send) -> None:
        await receive()
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})


class TestGetSessionCapabilities:

    def _make_ctx(self, *, supports: bool) -> MagicMock:
        ctx = MagicMock()
        ctx.session.check_client_capability.return_value = supports
        ctx.session.client_params.client_info = None
        return ctx

    def test_both_capabilities_true_when_client_declares_them(self):
        from api.endpoints.mcp_tools._base import get_session_capabilities

        caps = get_session_capabilities(self._make_ctx(supports=True))
        assert caps == {"elicitation": True, "tasks": True, "harness": "generic", "preset": None}

    def test_both_capabilities_false_when_client_declines(self):
        from api.endpoints.mcp_tools._base import get_session_capabilities

        caps = get_session_capabilities(self._make_ctx(supports=False))
        assert caps == {"elicitation": False, "tasks": False, "harness": "generic", "preset": None}

    def test_probe_failure_never_raises(self):
        from api.endpoints.mcp_tools._base import get_session_capabilities

        ctx = MagicMock()
        ctx.session.check_client_capability.side_effect = RuntimeError("no session")
        ctx.session.client_params.client_info = None
        caps = get_session_capabilities(ctx)
        assert caps == {"elicitation": False, "tasks": False, "harness": "generic", "preset": None}

    def test_harness_key_resolves_claude_code_from_client_info(self):
        from types import SimpleNamespace

        from api.endpoints.mcp_tools._base import get_session_capabilities

        ctx = MagicMock()
        ctx.session.check_client_capability.return_value = False
        ctx.session.client_params.client_info = SimpleNamespace(name="claude-code", version="2.1.199")
        caps = get_session_capabilities(ctx)
        assert caps["harness"] == "claude-code"
