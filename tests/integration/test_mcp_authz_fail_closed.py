# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_SYNTHETIC_TOOL_NAME = "sec9126_synthetic_unmapped_tool"


async def _synthetic_noop() -> dict:
    return {"sec9126_synthetic": True}


@pytest_asyncio.fixture
async def unmapped_tool_client(monkeypatch):
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base

    class _Holder:
        scopes: set[str] | None = None
        profile_toolset: frozenset[str] | None = None

    holder = _Holder()

    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: holder.scopes)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: holder.profile_toolset)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: "sec9126-tenant")
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    mcp_sdk_server.mcp._tool_manager.add_tool(_synthetic_noop, name=_SYNTHETIC_TOOL_NAME)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, holder
    finally:
        mcp_sdk_server.mcp._tool_manager.remove_tool(_SYNTHETIC_TOOL_NAME)




class TestLayerAUnmappedToolUnreachable:
    @pytest.mark.asyncio
    async def test_unmapped_registered_tool_is_not_dispatchable_on_any_auth_path(self, unmapped_tool_client):
        new_client, holder = unmapped_tool_client
        holder.scopes = None
        holder.profile_toolset = None

        async with new_client() as session:
            result = await session.call_tool(_SYNTHETIC_TOOL_NAME, {})

        assert result.is_error, "unmapped tool executed on the API-key bypass path (F1 fail-open)"
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "no authorization scope mapping" in joined

    @pytest.mark.asyncio
    async def test_unmapped_registered_tool_is_not_advertised(self, unmapped_tool_client):
        new_client, holder = unmapped_tool_client
        holder.scopes = None
        holder.profile_toolset = None

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert _SYNTHETIC_TOOL_NAME not in advertised

    @pytest.mark.asyncio
    async def test_unregistered_tool_name_keeps_sdk_error(self, unmapped_tool_client):
        new_client, holder = unmapped_tool_client
        holder.scopes = None
        holder.profile_toolset = None

        async with new_client() as session:
            result = await session.call_tool("sec9126_never_registered_zzz", {})

        assert result.is_error
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "no authorization scope mapping" not in joined




class TestLayerBResolverFailClosed:
    def test_unknown_auth_signal_resolves_to_empty_allow_set(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({}) == frozenset()
        assert _profile_toolset_from_state({"auth_method": "future-auth-path"}) == frozenset()

    def test_overshoot_guards_recognized_signals_unchanged(self):
        from api.endpoints.mcp_tools._base import (
            _CORE_PROFILE_TOOLS,
            _ORCHESTRATOR_PROFILE_TOOLS,
            _STANDARD_PROFILE_TOOLS,
            _profile_toolset_from_state,
        )

        assert _profile_toolset_from_state({"auth_method": "api_key"}) is None
        assert _profile_toolset_from_state({"auth_method": "jwt"}) == _STANDARD_PROFILE_TOOLS
        assert (
            _profile_toolset_from_state({"auth_method": "jwt", "scopes": ["mcp:agent"]}) == _ORCHESTRATOR_PROFILE_TOOLS
        )
        assert _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "core"}) == _CORE_PROFILE_TOOLS
        assert (
            _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "not_a_real_profile"})
            == _STANDARD_PROFILE_TOOLS
        )

    def test_startup_completeness_assert_raises_on_unmapped_tool(self):
        from api.endpoints import mcp_sdk_server

        fn = mcp_sdk_server._assert_tool_scope_completeness

        fn()

        mcp_sdk_server.mcp._tool_manager.add_tool(_synthetic_noop, name=_SYNTHETIC_TOOL_NAME)
        try:
            with pytest.raises(RuntimeError, match=_SYNTHETIC_TOOL_NAME):
                fn()
        finally:
            mcp_sdk_server.mcp._tool_manager.remove_tool(_SYNTHETIC_TOOL_NAME)
