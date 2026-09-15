# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


_EXPECTED_CORE = frozenset(
    {
        "health_check",
        "get_giljo_guide",
        "get_context",
        "list_projects",
        "create_project",
        "create_task",
        "update_task",
        "list_tasks",
        "search_memory",
        "get_job_mission",
        "report_progress",
        "complete_job",
        "write_project_closeout",
        "post_to_thread",
    }
)

_IMPLEMENT_GATE_TOOLS = ("stage_project", "get_implementation_prompt", "launch_implementation")


@pytest_asyncio.fixture
async def profile_mcp_client(db_manager, monkeypatch):
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
        scopes: set[str] | None = None
        profile_toolset: frozenset[str] | None = None

    holder = _Holder()

    monkeypatch.setattr(mcp_sdk_server, "_scopes_from_request", lambda _request: holder.scopes)
    monkeypatch.setattr(mcp_sdk_server, "_profile_toolset_from_request", lambda _request: holder.profile_toolset)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, holder
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




class TestCoreProfileRoster:
    @pytest.mark.asyncio
    async def test_core_tools_list_is_exactly_the_14_set(self, profile_mcp_client):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _CORE_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert advertised == _EXPECTED_CORE, (
            f"core profile saw {advertised - _EXPECTED_CORE} extra and missed {_EXPECTED_CORE - advertised}"
        )
        assert len(advertised) == 14
        assert "health_check" in advertised

    @pytest.mark.asyncio
    async def test_core_excludes_the_implement_gate_tools(self, profile_mcp_client):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _CORE_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        for gate_tool in _IMPLEMENT_GATE_TOOLS:
            assert gate_tool not in advertised, f"core profile leaked implement-gate tool {gate_tool}"




class TestFullProfileByteIdentity:
    @pytest.mark.asyncio
    async def test_full_profile_advertises_the_entire_surface(self, profile_mcp_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        new_client, holder = profile_mcp_client
        holder.profile_toolset = None

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert advertised == set(TOOL_SCOPES.keys()), (
            f"full profile is not byte-identical: missing {set(TOOL_SCOPES.keys()) - advertised}, "
            f"extra {advertised - set(TOOL_SCOPES.keys())}"
        )

    @pytest.mark.asyncio
    async def test_full_profile_can_dispatch_an_implement_gate_tool(self, profile_mcp_client):
        new_client, holder = profile_mcp_client
        holder.profile_toolset = None

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" not in joined




class TestOutOfProfileDispatchRejected:
    @pytest.mark.asyncio
    async def test_core_profile_rejects_out_of_profile_call(self, profile_mcp_client):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _CORE_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool(
                "spawn_job", {"project_id": str(uuid4()), "agent_name": "implementer", "mission": "probe"}
            )

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" in joined

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gate_tool", _IMPLEMENT_GATE_TOOLS)
    async def test_standard_profile_rejects_implement_gate_tools(self, profile_mcp_client, gate_tool):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _STANDARD_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool(gate_tool, {"project_id": str(uuid4())})

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" in joined




class TestProfileResolverPrecedence:
    def test_api_key_default_is_full(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "api_key"}) is None

    def test_jwt_without_scopes_is_standard(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "jwt"}) == _STANDARD_PROFILE_TOOLS

    def test_jwt_with_scopes_but_no_agent_is_standard(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write"]}
        assert _profile_toolset_from_state(state) == _STANDARD_PROFILE_TOOLS

    def test_jwt_with_mcp_agent_is_orchestrator(self):
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]}
        assert _profile_toolset_from_state(state) == _ORCHESTRATOR_PROFILE_TOOLS

    def test_jwt_with_mcp_agent_as_space_string_is_orchestrator(self):
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "scopes": "mcp:read mcp:write mcp:agent"}
        assert _profile_toolset_from_state(state) == _ORCHESTRATOR_PROFILE_TOOLS

    def test_api_key_with_mcp_agent_is_still_full(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "api_key", "scopes": ["mcp:agent"]}) is None

    def test_absent_auth_signal_fails_closed_to_empty(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({}) == frozenset()

    def test_declared_profile_wins_over_auth_default(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "tool_profile": "core"}
        assert _profile_toolset_from_state(state) == _CORE_PROFILE_TOOLS

    def test_declared_full_no_longer_widens_a_jwt_session(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "tool_profile": "full"}
        assert _profile_toolset_from_state(state) == _STANDARD_PROFILE_TOOLS

    def test_declared_full_clamps_a_jwt_agent_session_to_orchestrator(self):
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"], "tool_profile": "full"}
        resolved = _profile_toolset_from_state(state)
        assert resolved == _ORCHESTRATOR_PROFILE_TOOLS
        assert "launch_implementation" not in resolved

    def test_declared_full_still_widens_an_api_key_session(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "api_key", "tool_profile": "full"}) is None

    def test_declared_orchestrator_does_not_widen_a_standard_jwt_session(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "tool_profile": "orchestrator"}
        assert _profile_toolset_from_state(state) == _STANDARD_PROFILE_TOOLS

    def test_garbage_declared_profile_degrades_to_auth_default(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "not_a_real_profile"}) == (
            _STANDARD_PROFILE_TOOLS
        )
        assert _profile_toolset_from_state(
            {"auth_method": "future-auth-path", "tool_profile": "not_a_real_profile"}
        ) == (frozenset())




class TestProfileSetIntegrity:
    def test_core_and_standard_are_all_registered_tools(self):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _STANDARD_PROFILE_TOOLS

        registered = set(TOOL_SCOPES.keys())
        assert registered >= _CORE_PROFILE_TOOLS, f"core names not registered: {_CORE_PROFILE_TOOLS - registered}"
        assert registered >= _STANDARD_PROFILE_TOOLS, (
            f"standard names not registered: {_STANDARD_PROFILE_TOOLS - registered}"
        )

    def test_core_is_exactly_the_fourteen(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        assert _CORE_PROFILE_TOOLS == _EXPECTED_CORE
        assert len(_CORE_PROFILE_TOOLS) == 14

    def test_standard_is_a_superset_of_core(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _STANDARD_PROFILE_TOOLS

        assert _CORE_PROFILE_TOOLS <= _STANDARD_PROFILE_TOOLS

    def test_standard_excludes_the_implement_gate_tools(self):
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        for gate_tool in _IMPLEMENT_GATE_TOOLS:
            assert gate_tool not in _STANDARD_PROFILE_TOOLS, f"standard must exclude implement-gate tool {gate_tool}"

    def test_full_profile_is_the_none_sentinel(self):
        from api.endpoints.mcp_tools._base import PROFILE_FULL, TOOL_PROFILES

        assert TOOL_PROFILES[PROFILE_FULL] is None



_ORCHESTRATOR_MUST_SEE = (
    "health_check",
    "get_staging_instructions",
    "spawn_job",
    "update_project_mission",
    "stage_project",
    "get_implementation_prompt",
)


class TestOrchestratorProfileSet:
    def test_orchestrator_is_full_minus_launch_implementation_only(self):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES
        from api.endpoints.mcp_tools._base import _LAUNCH_GATE_TOOLS, _ORCHESTRATOR_PROFILE_TOOLS

        assert frozenset({"launch_implementation"}) == _LAUNCH_GATE_TOOLS
        assert frozenset(TOOL_SCOPES) - _LAUNCH_GATE_TOOLS == _ORCHESTRATOR_PROFILE_TOOLS
        assert "launch_implementation" not in _ORCHESTRATOR_PROFILE_TOOLS
        assert "stage_project" in _ORCHESTRATOR_PROFILE_TOOLS
        assert "get_implementation_prompt" in _ORCHESTRATOR_PROFILE_TOOLS

    def test_orchestrator_is_registered_in_the_profiles_map(self):
        from api.endpoints.mcp_tools._base import (
            _ORCHESTRATOR_PROFILE_TOOLS,
            PROFILE_ORCHESTRATOR,
            TOOL_PROFILES,
        )

        assert TOOL_PROFILES[PROFILE_ORCHESTRATOR] == _ORCHESTRATOR_PROFILE_TOOLS

    def test_every_profile_contains_health_check(self):
        from api.endpoints.mcp_tools._base import (
            PROFILE_CORE,
            PROFILE_FULL,
            PROFILE_ORCHESTRATOR,
            PROFILE_STANDARD,
            TOOL_PROFILES,
        )

        for name in (PROFILE_CORE, PROFILE_STANDARD, PROFILE_ORCHESTRATOR):
            assert "health_check" in TOOL_PROFILES[name], f"{name} missing health_check"
        assert TOOL_PROFILES[PROFILE_FULL] is None


class TestOrchestratorProfileTransportRegression:

    @pytest.mark.asyncio
    async def test_orchestrator_tools_list_shows_connector_flow_hides_launch(self, profile_mcp_client):
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _ORCHESTRATOR_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        missing = [t for t in _ORCHESTRATOR_MUST_SEE if t not in advertised]
        assert not missing, f"orchestrator tools/list missing connector-flow tools: {missing}"
        assert "launch_implementation" not in advertised, "orchestrator must NOT advertise the launch gate"

    @pytest.mark.asyncio
    async def test_resolver_output_feeds_the_filter_end_to_end(self, profile_mcp_client):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        resolved = _profile_toolset_from_state({"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]})
        new_client, holder = profile_mcp_client
        holder.profile_toolset = resolved

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert "health_check" in advertised
        assert "get_staging_instructions" in advertised
        assert "launch_implementation" not in advertised

    @pytest.mark.asyncio
    async def test_orchestrator_dispatch_rejects_launch_implementation(self, profile_mcp_client):
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _ORCHESTRATOR_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" in joined

    @pytest.mark.asyncio
    async def test_orchestrator_can_dispatch_stage_project(self, profile_mcp_client):
        new_client, holder = profile_mcp_client
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS

        holder.profile_toolset = _ORCHESTRATOR_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool("stage_project", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" not in joined




class TestDeclaredProfileStamping:
    def _session_row(self, session_data):
        class _Row:
            pass

        row = _Row()
        row.session_data = session_data
        return row

    def test_stamps_a_valid_declared_profile(self):
        from api.endpoints.mcp_sdk_server import _stamp_declared_profile

        scope = {"state": {"auth_method": "api_key"}}
        row = self._session_row({"client_info": {"name": "x", "giljo_tool_profile": "core"}})
        _stamp_declared_profile(scope, row)
        assert scope["state"]["tool_profile"] == "core"

    def test_ignores_a_garbage_declared_profile(self):
        from api.endpoints.mcp_sdk_server import _stamp_declared_profile

        scope = {"state": {}}
        row = self._session_row({"client_info": {"giljo_tool_profile": "not_a_profile"}})
        _stamp_declared_profile(scope, row)
        assert "tool_profile" not in scope["state"]

    def test_no_client_info_leaves_state_untouched(self):
        from api.endpoints.mcp_sdk_server import _stamp_declared_profile

        scope = {"state": {}}
        _stamp_declared_profile(scope, self._session_row({}))
        _stamp_declared_profile(scope, self._session_row(None))
        assert "tool_profile" not in scope["state"]


class TestDeclaredProfileEndToEnd:
    @pytest.mark.asyncio
    async def test_declared_core_profile_survives_initialize_to_next_request(self, db_manager, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "test_secret_key")
        from api.app_state import state
        from api.endpoints.mcp_sdk_server import MCPAuthMiddleware
        from api.endpoints.mcp_tools._base import TOOL_PROFILES, _profile_toolset_from_state
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
                    params={
                        "protocolVersion": "2025-06-18",
                        "capabilities": {},
                        "clientInfo": {"name": "e2e-probe", "version": "1.0", "giljo_tool_profile": "core"},
                    },
                ),
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
            )
            assert status2 == 200, f"tools/list request returned {status2}"
            toolset = _profile_toolset_from_state(captured)
            assert toolset == TOOL_PROFILES["core"], (
                f"declared core profile did not survive the round-trip; resolved={toolset}"
            )
            assert toolset is not None and len(toolset) == 14
        finally:
            state.db_manager = prior_db
