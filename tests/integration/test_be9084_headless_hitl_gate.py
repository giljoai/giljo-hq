# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


class _FakeRequest:

    def __init__(self, state: dict):
        self.scope = {"state": state}


async def _seed_headless_setting(db_manager, tenant_key: str, allow: bool) -> None:
    from giljo_mcp.services.settings_service import SettingsService

    async with db_manager.get_session_async() as db:
        svc = SettingsService(db, tenant_key)
        await svc.update_settings("security", {"allow_headless_launch": allow})


def _jwt_full_state(tenant_key: str) -> dict:
    return {
        "auth_method": "jwt",
        "scopes": ["mcp:read", "mcp:write", "mcp:agent"],
        "tool_profile": "full",
        "tenant_key": tenant_key,
    }


def _jwt_orchestrator_state(tenant_key: str) -> dict:
    return {
        "auth_method": "jwt",
        "scopes": ["mcp:read", "mcp:write", "mcp:agent"],
        "tenant_key": tenant_key,
    }


@pytest_asyncio.fixture
async def gate_client(db_manager, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tenant import TenantManager
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    class _Holder:
        pass

    holder = _Holder()
    holder.tenant_key = tenant_key
    holder.state = {}

    monkeypatch.setattr(mcp_sdk_server, "_request_from_context", lambda: _FakeRequest(holder.state))
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: holder.tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, holder
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




class TestDefaultHeadlessFence:
    @pytest.mark.asyncio
    async def test_no_row_advertises_launch_from_tools_list(self, gate_client):
        new_client, holder = gate_client
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert "launch_implementation" in advertised, "platform default must advertise the launch gate"
        assert "spawn_job" in advertised
        assert "stage_project" in advertised

    @pytest.mark.asyncio
    async def test_no_row_allows_launch_call(self, gate_client):
        new_client, holder = gate_client
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "HITL mode" not in joined, f"platform default must not be HITL-fenced, got: {joined!r}"

    @pytest.mark.asyncio
    async def test_explicit_false_toggle_still_blocks(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=False)
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "HITL mode" in joined

    @pytest.mark.asyncio
    async def test_explicit_false_toggle_still_hides_from_tools_list(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=False)
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        assert "launch_implementation" not in {t.name for t in result.tools}




class TestHeadlessOnAllows:
    @pytest.mark.asyncio
    async def test_toggle_on_advertises_launch_in_list(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=True)
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert "launch_implementation" in advertised, "Headless-ON tenant must see the launch gate"

    @pytest.mark.asyncio
    async def test_toggle_on_allows_launch_call(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=True)
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "HITL mode" not in joined, f"Headless-ON must not be HITL-fenced, got: {joined!r}"
        assert "gated by the human Implement step" not in joined




class TestToggleAdmitsWithNoDeclaration:
    @pytest.mark.asyncio
    async def test_toggle_on_with_no_declaration_advertises_launch(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=True)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)
        assert "tool_profile" not in holder.state, "this proof must not declare a profile at all"

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert "launch_implementation" in advertised, (
            "Headless-ON must admit the launch gate for an undeclared orchestrator session"
        )

    @pytest.mark.asyncio
    async def test_toggle_on_with_no_declaration_allows_dispatch(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=True)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" not in joined
        assert "HITL mode" not in joined

    @pytest.mark.asyncio
    async def test_toggle_explicit_off_with_no_declaration_still_hides_launch(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=False)
        holder.state = _jwt_orchestrator_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        assert "launch_implementation" not in {t.name for t in result.tools}

    @pytest.mark.asyncio
    async def test_self_declared_full_no_longer_widens_the_dispatch_gate(self, gate_client, db_manager):
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=False)
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            declared_full = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})
            holder.state = _jwt_orchestrator_state(holder.tenant_key)
            undeclared = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        declared_text = "\n".join(getattr(b, "text", "") for b in declared_full.content)
        undeclared_text = "\n".join(getattr(b, "text", "") for b in undeclared.content)
        assert "HITL mode" in declared_text
        assert "HITL mode" in undeclared_text




class TestApiKeyBypassUnaffected:
    @pytest.mark.asyncio
    async def test_api_key_sees_and_can_call_launch_even_with_headless_off(self, gate_client):
        new_client, holder = gate_client
        holder.state = {"auth_method": "api_key", "tenant_key": holder.tenant_key}

        async with new_client() as session:
            listed = await session.list_tools()
            advertised = {t.name for t in listed.tools}
            call = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        assert "launch_implementation" in advertised, "api_key operator must still see the launch gate"
        joined = "\n".join(getattr(b, "text", "") for b in call.content)
        assert "HITL mode" not in joined, "api_key operator must never be HITL-fenced"




class TestFencePredicate:
    @pytest.mark.asyncio
    async def test_request_none_is_never_fenced(self):
        from api.endpoints.mcp_sdk_server import _launch_gate_blocked

        assert await _launch_gate_blocked(None) is False

    @pytest.mark.asyncio
    async def test_api_key_state_is_never_fenced(self):
        from api.endpoints.mcp_sdk_server import _launch_gate_blocked

        blocked = await _launch_gate_blocked(_FakeRequest({"auth_method": "api_key", "tenant_key": "T"}))
        assert blocked is False

    @pytest.mark.asyncio
    async def test_jwt_without_tenant_fails_safe_blocked(self):
        from api.endpoints.mcp_sdk_server import _launch_gate_blocked

        assert await _launch_gate_blocked(_FakeRequest({"auth_method": "jwt"})) is True

    @pytest.mark.asyncio
    async def test_headless_read_fails_safe_to_blocked(self, monkeypatch):
        from api import app_state
        from api.endpoints import mcp_sdk_server

        class _Boom:
            def get_session_async(self):
                raise RuntimeError("db down")

        monkeypatch.setattr(app_state.state, "db_manager", _Boom())
        assert await mcp_sdk_server._headless_launch_allowed("some-tenant") is False




class TestRealMiddlewarePath:
    @pytest.mark.asyncio
    async def test_middleware_stamped_jwt_state_drives_the_fence(self, db_manager, monkeypatch):
        from sqlalchemy import select

        from api import app_state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware, _launch_gate_blocked
        from giljo_mcp.database import tenant_session_context
        from giljo_mcp.models.auth import User
        from giljo_mcp.tenant import TenantManager
        from tests.api.test_mcp_session import _seed_api_key
        from tests.integration.test_mcp_scope_filtering import (
            _CapturingInnerApp,
            _drive_middleware,
            _make_jwt,
        )

        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        monkeypatch.setenv("GILJO_MCP_CANONICAL_URI", "http://test/mcp")
        monkeypatch.setattr(app_state.state, "db_manager", db_manager)

        tenant_key = TenantManager.generate_tenant_key()
        await _seed_api_key(db_manager, tenant_key)
        async with db_manager.get_session_async() as db:
            with tenant_session_context(db, tenant_key):
                user = (await db.execute(select(User).where(User.tenant_key == tenant_key))).scalars().first()
                user_id = str(user.id)
        token = _make_jwt(
            aud="http://test/mcp", tenant_key=tenant_key, scope="mcp:read mcp:write mcp:agent", sub=user_id
        )

        inner = _CapturingInnerApp()
        status, _headers, _body = await _drive_middleware(
            MCPAuthMiddleware(app=inner), headers=[(b"authorization", f"Bearer {token}".encode())]
        )
        assert status == 200
        assert inner.scope_state.get("auth_method") == "jwt"
        assert inner.scope_state.get("tenant_key") == tenant_key

        stamped = _FakeRequest(inner.scope_state)
        assert await _launch_gate_blocked(stamped) is False

        await _seed_headless_setting(db_manager, tenant_key, allow=False)
        assert await _launch_gate_blocked(stamped) is True




class _StubUser:
    def __init__(self, tenant_key: str):
        self.tenant_key = tenant_key
        self.username = "be9084_admin"


class TestHeadlessLaunchEndpoint:
    @pytest.mark.asyncio
    async def test_get_defaults_to_true_when_unset(self, db_session):
        from api.endpoints.user_settings import get_headless_launch
        from giljo_mcp.tenant import TenantManager

        user = _StubUser(TenantManager.generate_tenant_key())
        resp = await get_headless_launch(current_user=user, db=db_session)
        assert resp.allow_headless_launch is True

    @pytest.mark.asyncio
    async def test_put_sets_toggle_and_preserves_sibling_security_keys(self, db_session):
        from api.endpoints.user_settings import HeadlessLaunchUpdateRequest, get_headless_launch, update_headless_launch
        from giljo_mcp.services.settings_service import SettingsService
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        svc = SettingsService(db_session, tenant_key)
        await svc.update_settings("security", {"cookie_domain_whitelist": ["app.example.com"]})

        user = _StubUser(tenant_key)
        resp = await update_headless_launch(
            HeadlessLaunchUpdateRequest(allow_headless_launch=True), current_user=user, db=db_session
        )
        assert resp.allow_headless_launch is True

        security = await svc.get_settings("security")
        assert security["allow_headless_launch"] is True
        assert security["cookie_domain_whitelist"] == ["app.example.com"]

        got = await get_headless_launch(current_user=user, db=db_session)
        assert got.allow_headless_launch is True

    @pytest.mark.asyncio
    async def test_put_false_turns_it_back_off(self, db_session):
        from api.endpoints.user_settings import HeadlessLaunchUpdateRequest, get_headless_launch, update_headless_launch
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        user = _StubUser(tenant_key)
        await update_headless_launch(
            HeadlessLaunchUpdateRequest(allow_headless_launch=True), current_user=user, db=db_session
        )
        await update_headless_launch(
            HeadlessLaunchUpdateRequest(allow_headless_launch=False), current_user=user, db=db_session
        )
        got = await get_headless_launch(current_user=user, db=db_session)
        assert got.allow_headless_launch is False

    @pytest.mark.asyncio
    async def test_put_stamps_the_explicit_marker(self, db_session):
        from api.endpoints.user_settings import HeadlessLaunchUpdateRequest, update_headless_launch
        from giljo_mcp.services.settings_service import SettingsService
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        user = _StubUser(tenant_key)
        await update_headless_launch(
            HeadlessLaunchUpdateRequest(allow_headless_launch=False), current_user=user, db=db_session
        )

        svc = SettingsService(db_session, tenant_key)
        security = await svc.get_settings("security")
        assert security["allow_headless_launch_explicit"] is True

    @pytest.mark.asyncio
    async def test_unrelated_security_writer_does_not_set_the_explicit_marker(self, db_session):
        from giljo_mcp.services.settings_service import SettingsService
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        svc = SettingsService(db_session, tenant_key)
        await svc.update_settings("security", {"cookie_domain_whitelist": ["app.example.com"]})

        security = await svc.get_settings("security")
        assert security["allow_headless_launch"] is False, "schema default, NOT a deliberate opt-out"
        assert security["allow_headless_launch_explicit"] is False, "never touched via the dedicated PUT"

    @pytest.mark.asyncio
    async def test_explicit_off_survives_a_simulated_redeploy(self, db_session):
        from api.endpoints.user_settings import HeadlessLaunchUpdateRequest, get_headless_launch, update_headless_launch
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        user = _StubUser(tenant_key)
        await update_headless_launch(
            HeadlessLaunchUpdateRequest(allow_headless_launch=False), current_user=user, db=db_session
        )

        got = await get_headless_launch(current_user=_StubUser(tenant_key), db=db_session)
        assert got.allow_headless_launch is False
