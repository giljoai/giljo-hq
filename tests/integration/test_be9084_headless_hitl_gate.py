# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9084 — default-HITL launch fence at the MCP gate.

The bypass this closes: a jwt/OAuth mcp:agent session that declares
``giljo_tool_profile="full"`` in its initialize clientInfo widens its profile to
the full surface (``_profile_toolset_from_state`` -> ``None``), which would
otherwise re-expose ``launch_implementation`` and let a CLI agent self-cross the
human Implement gate.

The fence (``mcp_sdk_server._launch_gate_blocked``) enforces HITL by DEFAULT for
every jwt session, regardless of declared profile, keyed on the tenant's
``security.allow_headless_launch`` toggle (default ``False``). The operator
api_key path is never fenced (full bypass), and ``_profile_toolset_from_state`` is
left untouched (the operator-widening path stays — locked by
``test_be8003k_tool_profiles``).

Failing-layer discipline (CLAUDE.md): these drive the REAL scope-gated tools/list
filter and tools/call dispatch gate (the layer the fence lives in) with a real jwt
request state and a REAL ``SettingsService`` read of a committed settings row —
two-sided (default HITL rejects; toggle ON allows) plus the api_key bypass.
Parallel-safe: a unique ``tenant_key`` per test, no module-level mutable state.
Edition Scope: Both.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


class _FakeRequest:
    """Minimal StarletteRequest stand-in carrying ASGI scope state for the gate.

    The real gate resolves the caller's state off ``request.scope['state']`` (which
    ``MCPAuthMiddleware`` stamps in production). The in-memory MCP client has no HTTP
    request, so the fixture monkeypatches ``_request_from_context`` to hand the gate
    THIS object — letting ``_scopes_from_request`` / ``_profile_toolset_from_request``
    and the BE-9084 fence all run for real against a configurable session shape.
    """

    def __init__(self, state: dict):
        self.scope = {"state": state}


async def _seed_headless_setting(db_manager, tenant_key: str, allow: bool) -> None:
    """Commit a ``security.allow_headless_launch`` row for the tenant.

    Uses its own committed session so the gate's independent session (opened inside
    ``_headless_launch_allowed``) reads the persisted value — mirroring production,
    where the toggle is written by the settings UI and read at a later MCP call.
    """
    from giljo_mcp.services.settings_service import SettingsService

    async with db_manager.get_session_async() as db:
        svc = SettingsService(db, tenant_key)
        await svc.update_settings("security", {"allow_headless_launch": allow})


def _jwt_full_state(tenant_key: str) -> dict:
    """A jwt/OAuth mcp:agent session that declared the full profile — the bypass shape.

    ``mcp:agent`` in scope + ``tool_profile="full"`` is exactly the session that
    reaches ``launch_implementation`` today (scope allows it, declared-full removes
    the profile restriction). The fence must gate it back to HITL by default.
    """
    return {
        "auth_method": "jwt",
        "scopes": ["mcp:read", "mcp:write", "mcp:agent"],
        "tool_profile": "full",
        "tenant_key": tenant_key,
    }


@pytest_asyncio.fixture
async def gate_client(db_manager, monkeypatch):
    """In-memory MCP client wired so the REAL scope+profile+fence gate runs against a
    configurable request state and a real tenant DB.

    Returns ``(new_client, holder)``. Set ``holder.state`` to the ASGI scope state
    the gate should see; ``holder.tenant_key`` is a fresh tenant for seeding the
    settings row. ``_resolve_tenant`` / ``_resolve_user_id`` are pinned so an ALLOWED
    dispatch resolves tenant off the in-memory transport (the fence's own settings
    read is independent — it keys on ``holder.state['tenant_key']``).
    """
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


# ---------------------------------------------------------------------------
# Default HITL (no toggle / toggle False): the launch gate is fenced for a
# full-declaring jwt session — hidden from tools/list AND rejected at dispatch.
# ---------------------------------------------------------------------------


class TestDefaultHitlFence:
    @pytest.mark.asyncio
    async def test_default_hitl_hides_launch_from_tools_list(self, gate_client):
        """No settings row -> default False (HITL). A full-declaring jwt session must
        NOT be advertised ``launch_implementation`` — but the fence is SURGICAL: the
        rest of its full agent surface stays visible."""
        new_client, holder = gate_client
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert "launch_implementation" not in advertised, "default HITL must hide the launch gate"
        assert "spawn_job" in advertised, "the fence must not strip the rest of the agent surface"
        assert "stage_project" in advertised

    @pytest.mark.asyncio
    async def test_default_hitl_rejects_launch_call(self, gate_client):
        """A crafted tools/call to ``launch_implementation`` is server-rejected with the
        HITL fence text (defense-in-depth: hiding from list alone is insufficient)."""
        new_client, holder = gate_client
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "HITL mode" in joined, f"expected the BE-9084 fence rejection, got: {joined!r}"

    @pytest.mark.asyncio
    async def test_explicit_false_toggle_also_blocks(self, gate_client, db_manager):
        """An explicitly-persisted ``allow_headless_launch=False`` blocks identically to
        the no-row default (two ways to express HITL converge)."""
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=False)
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "HITL mode" in joined


# ---------------------------------------------------------------------------
# Toggle ON: the same full-declaring jwt session is allowed to see + call the
# launch gate (the opt-in Headless path).
# ---------------------------------------------------------------------------


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
        """With Headless ON, the fence must NOT fire. The call may still error downstream
        on the fabricated project_id, but never with the HITL fence text."""
        new_client, holder = gate_client
        await _seed_headless_setting(db_manager, holder.tenant_key, allow=True)
        holder.state = _jwt_full_state(holder.tenant_key)

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "HITL mode" not in joined, f"Headless-ON must not be HITL-fenced, got: {joined!r}"
        assert "gated by the human Implement step" not in joined


# ---------------------------------------------------------------------------
# Operator bypass: an api_key session is NEVER fenced, even with Headless OFF.
# ---------------------------------------------------------------------------


class TestApiKeyBypassUnaffected:
    @pytest.mark.asyncio
    async def test_api_key_sees_and_can_call_launch_even_with_headless_off(self, gate_client):
        """Even at the default HITL posture, an api_key operator session keeps the full
        CLI bypass — the fence only applies to jwt sessions."""
        new_client, holder = gate_client
        holder.state = {"auth_method": "api_key", "tenant_key": holder.tenant_key}

        async with new_client() as session:
            listed = await session.list_tools()
            advertised = {t.name for t in listed.tools}
            call = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        assert "launch_implementation" in advertised, "api_key operator must still see the launch gate"
        joined = "\n".join(getattr(b, "text", "") for b in call.content)
        assert "HITL mode" not in joined, "api_key operator must never be HITL-fenced"


# ---------------------------------------------------------------------------
# Fence predicate + fail-safe unit coverage (no transport, no seeded row).
# ---------------------------------------------------------------------------


class TestFencePredicate:
    @pytest.mark.asyncio
    async def test_request_none_is_never_fenced(self):
        """The in-memory/request-less path is never fenced (no real session to gate)."""
        from api.endpoints.mcp_sdk_server import _launch_gate_blocked

        assert await _launch_gate_blocked(None) is False

    @pytest.mark.asyncio
    async def test_api_key_state_is_never_fenced(self):
        from api.endpoints.mcp_sdk_server import _launch_gate_blocked

        blocked = await _launch_gate_blocked(_FakeRequest({"auth_method": "api_key", "tenant_key": "T"}))
        assert blocked is False

    @pytest.mark.asyncio
    async def test_jwt_without_tenant_fails_safe_blocked(self):
        """A jwt session with no resolvable tenant_key fails SAFE (blocked) — the gate
        must never open when it cannot identify whose toggle to read."""
        from api.endpoints.mcp_sdk_server import _launch_gate_blocked

        assert await _launch_gate_blocked(_FakeRequest({"auth_method": "jwt"})) is True

    @pytest.mark.asyncio
    async def test_headless_read_fails_safe_to_blocked(self, monkeypatch):
        """Any error resolving the setting resolves to False (HITL) — the gate never
        opens on a failed lookup."""
        from api import app_state
        from api.endpoints import mcp_sdk_server

        class _Boom:
            def get_session_async(self):
                raise RuntimeError("db down")

        monkeypatch.setattr(app_state.state, "db_manager", _Boom())
        assert await mcp_sdk_server._headless_launch_allowed("some-tenant") is False


# ---------------------------------------------------------------------------
# REAL MCPAuthMiddleware path: prove the fence keys on
# the state a REAL Bearer-JWT session gets stamped by MCPAuthMiddleware — so the
# blocking proof never leans on the in-memory ``request is None`` carve-out.
# ---------------------------------------------------------------------------


class TestRealMiddlewarePath:
    @pytest.mark.asyncio
    async def test_middleware_stamped_jwt_state_drives_the_fence(self, db_manager, monkeypatch):
        """An aud-bound Bearer JWT (mcp:agent) through the REAL MCPAuthMiddleware is
        stamped ``auth_method="jwt"`` + ``tenant_key``; the BE-9084 fence then blocks
        (default HITL) and allows (Headless ON) for THAT exact stamped state — no fake
        request, no ``None`` carve-out."""
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

        # A real, active user for the tenant: with db_manager wired the middleware runs
        # the FULL validate_principal (user-exists + is-active), so the token's sub must
        # name a live user — this is the faithful authenticated-jwt path, not decode-only.
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
        # The state the fence keys on, produced by the REAL middleware (not fabricated).
        assert inner.scope_state.get("auth_method") == "jwt"
        assert inner.scope_state.get("tenant_key") == tenant_key

        stamped = _FakeRequest(inner.scope_state)
        # Default HITL (no settings row) -> the fence BLOCKS this real jwt state.
        assert await _launch_gate_blocked(stamped) is True

        # Opt the tenant into Headless -> the same real jwt state is ALLOWED.
        await _seed_headless_setting(db_manager, tenant_key, allow=True)
        assert await _launch_gate_blocked(stamped) is False


# ---------------------------------------------------------------------------
# REST toggle endpoint: default False, and the PUT read-modify-write never
# clobbers the sibling ``security`` key (cookie_domain_whitelist).
# ---------------------------------------------------------------------------


class _StubUser:
    def __init__(self, tenant_key: str):
        self.tenant_key = tenant_key
        self.username = "be9084_admin"


class TestHeadlessLaunchEndpoint:
    @pytest.mark.asyncio
    async def test_get_defaults_to_false_when_unset(self, db_session):
        from api.endpoints.user_settings import get_headless_launch
        from giljo_mcp.tenant import TenantManager

        user = _StubUser(TenantManager.generate_tenant_key())
        resp = await get_headless_launch(current_user=user, db=db_session)
        assert resp.allow_headless_launch is False

    @pytest.mark.asyncio
    async def test_put_sets_toggle_and_preserves_sibling_security_keys(self, db_session):
        from api.endpoints.user_settings import HeadlessLaunchUpdateRequest, get_headless_launch, update_headless_launch
        from giljo_mcp.services.settings_service import SettingsService
        from giljo_mcp.tenant import TenantManager

        tenant_key = TenantManager.generate_tenant_key()
        # Seed an existing security blob (cookie whitelist the PUT must NOT wipe).
        svc = SettingsService(db_session, tenant_key)
        await svc.update_settings("security", {"cookie_domain_whitelist": ["app.example.com"]})

        user = _StubUser(tenant_key)
        resp = await update_headless_launch(
            HeadlessLaunchUpdateRequest(allow_headless_launch=True), current_user=user, db=db_session
        )
        assert resp.allow_headless_launch is True

        # Toggle persisted AND the cookie whitelist survived the read-modify-write.
        security = await svc.get_settings("security")
        assert security["allow_headless_launch"] is True
        assert security["cookie_domain_whitelist"] == ["app.example.com"]

        # GET reflects the new value.
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
