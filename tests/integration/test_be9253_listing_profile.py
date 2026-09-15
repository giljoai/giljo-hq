# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest

from tests.integration.test_be8003k_tool_profiles import profile_mcp_client  # noqa: F401


_EXPECTED_LISTING = frozenset(
    {
        "health_check",
        "get_giljo_guide",
        "get_context",
        "list_projects",
        "create_project",
        "update_project",
        "list_tasks",
        "create_task",
        "update_task",
        "search_memory",
        "get_roadmap",
    }
)




class TestListingProfileRoster:
    @pytest.mark.asyncio
    async def test_listing_tools_list_is_exactly_the_named_set(self, profile_mcp_client):  # noqa: F811
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _LISTING_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert advertised == _EXPECTED_LISTING, (
            f"listing profile saw {sorted(advertised - _EXPECTED_LISTING)} extra and "
            f"missed {sorted(_EXPECTED_LISTING - advertised)}"
        )

    @pytest.mark.asyncio
    async def test_listing_hides_the_orchestration_surface(self, profile_mcp_client):  # noqa: F811
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _LISTING_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        for hidden in (
            "spawn_job",
            "stage_project",
            "get_implementation_prompt",
            "launch_implementation",
            "start_chain_run",
        ):
            assert hidden not in advertised, f"listing profile leaked orchestration tool {hidden}"

    def test_listing_roster_matches_the_source_constant(self):
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        assert _LISTING_PROFILE_TOOLS == _EXPECTED_LISTING

    def test_listing_is_registered_in_the_profiles_map(self):
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS, PROFILE_LISTING, TOOL_PROFILES

        assert PROFILE_LISTING == "listing"
        assert TOOL_PROFILES[PROFILE_LISTING] == _LISTING_PROFILE_TOOLS

    def test_listing_names_are_all_registered_tools(self):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        unregistered = _LISTING_PROFILE_TOOLS - set(TOOL_SCOPES)
        assert not unregistered, f"listing names absent from TOOL_SCOPES: {sorted(unregistered)}"

    def test_listing_requires_no_agent_scope(self):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        used = {TOOL_SCOPES[name] for name in _LISTING_PROFILE_TOOLS}
        assert used == {"mcp:read", "mcp:write"}, f"listing uses unexpected scopes: {sorted(used)}"

    def test_listing_is_a_subset_of_orchestrator(self):
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS, _ORCHESTRATOR_PROFILE_TOOLS

        assert _LISTING_PROFILE_TOOLS <= _ORCHESTRATOR_PROFILE_TOOLS




class TestListingOutOfProfileDispatchRejected:
    @pytest.mark.asyncio
    async def test_listing_rejects_a_crafted_out_of_profile_call(self, profile_mcp_client):  # noqa: F811
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _LISTING_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool(
                "spawn_job", {"project_id": str(uuid4()), "agent_name": "implementer", "mission": "probe"}
            )

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" in joined

    @pytest.mark.asyncio
    async def test_listing_can_dispatch_update_project(self, profile_mcp_client):  # noqa: F811
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _LISTING_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool("update_project", {"project_id": str(uuid4()), "status": "active"})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" not in joined




def _stamp(query: str, state: dict) -> dict:
    from api.endpoints.mcp_sdk_server import _stamp_url_profile

    scope = {"query_string": query.encode("ascii"), "state": dict(state)}
    _stamp_url_profile(scope)
    return scope["state"]


class TestUrlProfileNarrowing:
    def test_connector_session_narrows_to_listing(self):
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=listing", {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]})
        assert state["tool_profile"] == "listing"
        assert _profile_toolset_from_state(state) == _LISTING_PROFILE_TOOLS

    def test_api_key_session_narrows_to_listing(self):
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=listing", {"auth_method": "api_key"})
        assert _profile_toolset_from_state(state) == _LISTING_PROFILE_TOOLS

    def test_no_query_string_leaves_state_byte_identical(self):
        before = {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]}
        assert _stamp("", before) == before

    def test_unrelated_query_string_leaves_state_byte_identical(self):
        before = {"auth_method": "jwt", "scopes": ["mcp:agent"]}
        assert _stamp("foo=bar&baz=1", before) == before

    def test_garbage_profile_name_is_ignored(self):
        state = _stamp("profile=not_a_real_profile", {"auth_method": "jwt", "scopes": ["mcp:agent"]})
        assert "tool_profile" not in state


class TestUrlProfileRefusesToWiden:

    def test_profile_full_never_reaches_the_unrestricted_sentinel(self):
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=full", {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]})
        assert "tool_profile" not in state
        resolved = _profile_toolset_from_state(state)
        assert resolved is not None, "?profile=full widened a jwt session to the unrestricted surface"
        assert resolved == _ORCHESTRATOR_PROFILE_TOOLS

    def test_profile_full_cannot_widen_a_declared_core_session(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=full", {"auth_method": "jwt", "tool_profile": "core"})
        assert state["tool_profile"] == "core"
        assert _profile_toolset_from_state(state) == _CORE_PROFILE_TOOLS

    def test_listing_is_refused_when_it_would_widen_a_standard_session(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=listing", {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write"]})
        assert "tool_profile" not in state
        assert _profile_toolset_from_state(state) == _STANDARD_PROFILE_TOOLS

    def test_listing_is_refused_when_it_would_widen_a_declared_core_session(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=listing", {"auth_method": "jwt", "tool_profile": "core"})
        assert state["tool_profile"] == "core"
        assert _profile_toolset_from_state(state) == _CORE_PROFILE_TOOLS

    def test_url_vehicle_cannot_escape_the_fail_closed_floor(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        for query in ("profile=listing", "profile=full", "profile=core", "profile=orchestrator"):
            state = _stamp(query, {"auth_method": "future-auth-path"})
            assert "tool_profile" not in state, f"{query} escaped the fail-closed floor"
            assert _profile_toolset_from_state(state) == frozenset()

    def test_every_profile_name_is_narrow_only_from_every_baseline(self):
        from api.endpoints.mcp_tools._base import TOOL_PROFILES, _profile_toolset_from_state

        baselines = (
            {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]},
            {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write"]},
            {"auth_method": "jwt"},
            {"auth_method": "api_key"},
            {"auth_method": "jwt", "tool_profile": "core"},
            {"auth_method": "jwt", "tool_profile": "full"},
            {"auth_method": "future-auth-path"},
            {},
        )
        universe = frozenset(TOOL_PROFILES) | {"not_a_real_profile"}
        for baseline in baselines:
            before = _profile_toolset_from_state(baseline)
            for name in universe:
                after = _profile_toolset_from_state(_stamp(f"profile={name}", baseline))
                if before is None:
                    continue
                assert after is not None, f"?profile={name} widened {baseline} to the unrestricted surface"
                assert after <= before, f"?profile={name} widened {baseline} by {sorted(after - before)}"




class TestUrlProfileEndToEnd:
    @staticmethod
    async def _drive(db_manager, monkeypatch, *, query_string: bytes, client_info: dict):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from tests.api.test_mcp_session import _drive_middleware_with_body, _jsonrpc_body, _seed_api_key

        raw_key, _tenant_key = await _seed_api_key(db_manager)
        prior_db = state.db_manager
        state.db_manager = db_manager
        try:
            captured: dict = {}

            class _StateCapturingProbe:
                async def __call__(self, scope, receive, send) -> None:
                    captured.clear()
                    captured.update(dict(scope.get("state") or {}))
                    await receive()
                    await send({"type": "http.response.start", "status": 200, "headers": []})
                    await send({"type": "http.response.body", "body": b'{"jsonrpc":"2.0","id":1,"result":{}}'})

            mw = MCPAuthMiddleware(app=_StateCapturingProbe())
            status, headers, _body = await _drive_middleware_with_body(
                mw,
                headers=[(b"x-api-key", raw_key.encode()), (b"content-type", b"application/json")],
                body=_jsonrpc_body(
                    "initialize",
                    params={"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": client_info},
                ),
                query_string=query_string,
            )
            assert status == 200, f"initialize returned {status}"
            session_id = headers.get("mcp-session-id")
            assert session_id, "initialize must issue Mcp-Session-Id"

            status2, _h2, _b2 = await _drive_middleware_with_body(
                mw,
                headers=[
                    (b"x-api-key", raw_key.encode()),
                    (b"content-type", b"application/json"),
                    (b"mcp-session-id", session_id.encode()),
                ],
                body=_jsonrpc_body("tools/list", params={}),
                query_string=query_string,
            )
            assert status2 == 200, f"tools/list request returned {status2}"
            return captured
        finally:
            state.db_manager = prior_db

    @pytest.mark.asyncio
    async def test_query_string_survives_to_the_resolver(self, db_manager, monkeypatch):
        from api.endpoints.mcp_tools._base import TOOL_PROFILES, _profile_toolset_from_state

        captured = await self._drive(
            db_manager,
            monkeypatch,
            query_string=b"profile=listing",
            client_info={"name": "e2e-probe", "version": "1.0"},
        )
        assert captured.get("tool_profile") == "listing"
        toolset = _profile_toolset_from_state(captured)
        assert toolset == TOOL_PROFILES["listing"]
        assert toolset == _EXPECTED_LISTING

    @pytest.mark.asyncio
    async def test_no_query_string_is_unchanged_from_today(self, db_manager, monkeypatch):
        from api.endpoints.mcp_tools._base import TOOL_PROFILES, _profile_toolset_from_state

        captured = await self._drive(
            db_manager,
            monkeypatch,
            query_string=b"",
            client_info={"name": "e2e-probe", "version": "1.0", "giljo_tool_profile": "core"},
        )
        assert _profile_toolset_from_state(captured) == TOOL_PROFILES["core"]

    @pytest.mark.asyncio
    async def test_query_string_cannot_widen_a_declared_core_session(self, db_manager, monkeypatch):
        from api.endpoints.mcp_tools._base import TOOL_PROFILES, _profile_toolset_from_state

        captured = await self._drive(
            db_manager,
            monkeypatch,
            query_string=b"profile=full",
            client_info={"name": "e2e-probe", "version": "1.0", "giljo_tool_profile": "core"},
        )
        assert captured.get("tool_profile") == "core"
        toolset = _profile_toolset_from_state(captured)
        assert toolset is not None, "?profile=full widened a declared-core session through the real middleware"
        assert toolset == TOOL_PROFILES["core"]




class TestExistingProfilesUnaffected:
    def test_core_standard_orchestrator_full_rosters_unchanged(self):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES
        from api.endpoints.mcp_tools._base import (
            _LAUNCH_GATE_TOOLS,
            PROFILE_CORE,
            PROFILE_FULL,
            PROFILE_ORCHESTRATOR,
            PROFILE_STANDARD,
            TOOL_PROFILES,
        )

        assert len(TOOL_PROFILES[PROFILE_CORE]) == 14
        assert TOOL_PROFILES[PROFILE_CORE] <= TOOL_PROFILES[PROFILE_STANDARD]
        assert TOOL_PROFILES[PROFILE_ORCHESTRATOR] == frozenset(TOOL_SCOPES) - _LAUNCH_GATE_TOOLS
        assert TOOL_PROFILES[PROFILE_FULL] is None

    def test_adding_listing_did_not_change_auth_derived_resolution(self):
        from api.endpoints.mcp_tools._base import (
            _ORCHESTRATOR_PROFILE_TOOLS,
            _STANDARD_PROFILE_TOOLS,
            _profile_toolset_from_state,
        )

        assert _profile_toolset_from_state({"auth_method": "api_key"}) is None
        assert _profile_toolset_from_state({"auth_method": "jwt"}) == _STANDARD_PROFILE_TOOLS
        assert (
            _profile_toolset_from_state({"auth_method": "jwt", "scopes": ["mcp:agent"]}) == _ORCHESTRATOR_PROFILE_TOOLS
        )
        assert _profile_toolset_from_state({}) == frozenset()
        assert _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "full"}) == _STANDARD_PROFILE_TOOLS
