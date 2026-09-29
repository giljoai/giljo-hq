# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid

import bcrypt
import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


async def _seed_user(db_manager, tenant_key: str, *, must_change_password: bool) -> str:
    from giljo_mcp.models import User
    from giljo_mcp.models.organizations import Organization

    suffix = uuid.uuid4().hex[:8]
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        org = Organization(
            name=f"BE-9698 MCP Org {suffix}",
            slug=f"be9698-mcp-org-{suffix}",
            tenant_key=tenant_key,
            is_active=True,
        )
        session.add(org)
        await session.flush()
        user = User(
            username=f"be9698_mcp_user_{suffix}",
            email=f"be9698_mcp_{suffix}@example.com",
            password_hash=bcrypt.hashpw(b"whatever12345", bcrypt.gensalt()).decode("utf-8"),
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
            must_change_password=must_change_password,
        )
        session.add(user)
        await session.commit()
        return user.id


class TestMiddlewareStampsMustChangePassword:

    async def test_jwt_path_stamps_the_flag(self, db_manager, monkeypatch):
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from giljo_mcp.auth.jwt_manager import JWTManager
        from giljo_mcp.tenant import TenantManager

        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        tenant_key = TenantManager.generate_tenant_key()
        user_id = await _seed_user(db_manager, tenant_key, must_change_password=True)
        token = JWTManager.create_access_token(
            user_id=user_id, username="x", role="developer", tenant_key=tenant_key, audience="http://test/mcp"
        )

        captured = {}

        async def inner_app(scope, receive, send):
            captured["state"] = dict(scope.get("state", {}))
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})

        mw = MCPAuthMiddleware(inner_app)
        body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).encode()
        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "method": "POST",
            "path": "/mcp",
            "raw_path": b"/mcp",
            "query_string": b"",
            "headers": [
                (b"authorization", f"Bearer {token}".encode()),
                (b"host", b"test"),
                (b"content-type", b"application/json"),
            ],
            "client": ("127.0.0.1", 1),
            "server": ("test", 80),
            "scheme": "http",
            "root_path": "",
        }
        body_sent = {"done": False}

        async def receive():
            if body_sent["done"]:
                return {"type": "http.disconnect"}
            body_sent["done"] = True
            return {"type": "http.request", "body": body, "more_body": False}

        async def send(_message):
            pass

        await mw(scope, receive, send)

        assert captured["state"]["must_change_password"] is True


@pytest_asyncio.fixture
async def act_first_mcp_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from giljo_mcp.tenant import TenantManager
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    class _RequestState:

        must_change_password: bool | None = None

        @property
        def scope(self):
            return {"state": {"must_change_password": self.must_change_password}}

    holder = _RequestState()

    monkeypatch.setattr(mcp_sdk_server, "_request_from_context", lambda: holder)
    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: None)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, holder
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


class TestMcpPasswordChangeGateBlocksToolCalls:
    async def test_gated_call_is_refused_with_password_change_required(self, act_first_mcp_client):
        new_client, holder = act_first_mcp_client
        holder.must_change_password = True

        async with new_client() as session:
            result = await session.call_tool("get_giljo_guide", {})

        assert result.is_error is True
        text = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "PASSWORD_CHANGE_REQUIRED" in text, text

    async def test_gated_call_can_still_use_the_allowlisted_health_check_tool(self, act_first_mcp_client):
        new_client, holder = act_first_mcp_client
        holder.must_change_password = True

        async with new_client() as session:
            result = await session.call_tool("health_check", {})

        assert result.is_error is not True, getattr(result, "content", None)

    async def test_ungated_call_succeeds(self, act_first_mcp_client):
        new_client, holder = act_first_mcp_client
        holder.must_change_password = False

        async with new_client() as session:
            result = await session.call_tool("get_giljo_guide", {})

        assert result.is_error is not True, getattr(result, "content", None)

    async def test_after_the_stamped_flag_clears_the_same_tool_call_succeeds(self, act_first_mcp_client):
        new_client, holder = act_first_mcp_client
        holder.must_change_password = True

        async with new_client() as session:
            blocked = await session.call_tool("get_giljo_guide", {})
        assert blocked.is_error is True

        holder.must_change_password = False

        async with new_client() as session:
            result = await session.call_tool("get_giljo_guide", {})
        assert result.is_error is not True, getattr(result, "content", None)


class TestMcpActFirstGateRequestlessTransportIsUnaffected:
    async def test_no_request_context_never_blocks(self):
        from api.endpoints import mcp_sdk_server

        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
            result = await session.call_tool("health_check", {})

        assert result.is_error is not True, getattr(result, "content", None)
