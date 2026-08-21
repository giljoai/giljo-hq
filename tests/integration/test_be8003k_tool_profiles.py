# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-8003k — server-enforced tool PROFILES (core / standard / full).

Profiles are a curated tool-name lens evaluated ALONGSIDE the 3 API-0021b auth
scopes: the effective set is the intersection scope-filter ∩ profile. Per the
CLAUDE.md failing-layer rule, the enforcement lives at the FastMCP transport
boundary (the tools/list filter + the tools/call dispatch gate) and in the
``_base`` resolver, so these tests drive that boundary — a roster-style lock on
core, a byte-identity floor on full, and a dispatch-gate rejection for an
out-of-profile call — mirroring test_mcp_scope_filtering.py's S4-S9.

Parallel-safe: no DB writes, no module-level mutable state; each test pins its
own profile/scope via the ``profile_mcp_client`` holder. Edition Scope: Both.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


# The exact 14-tool "one tool per intent" guided loop (EM decision, BE-8003k;
# BE-9017 added health_check as every prompt's step-1 fresh-connect probe).
# Hardcoded here as the ROSTER LOCK: a change to the core profile must break this
# test deliberately, not slip through.
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

# The three implement-gate tools that must be server-excluded from core AND
# standard (WO-8003k DoD #3 — turning the advisory exclusion into an enforced one).
_IMPLEMENT_GATE_TOOLS = ("stage_project", "implement_project", "launch_implementation")


@pytest_asyncio.fixture
async def profile_mcp_client(db_manager, monkeypatch):
    """In-memory MCP client that lets each test pin a profile allow-set + scope.

    Returns (new_client, holder). ``holder.scopes`` is what ``_scopes_from_request``
    returns (None = API-key bypass, so the scope axis does not interfere with the
    profile assertion). ``holder.profile_toolset`` is what
    ``_profile_toolset_from_request`` returns (None = full / no restriction, a
    frozenset = that profile).
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
        scopes: set[str] | None = None  # API-key bypass by default
        profile_toolset: frozenset[str] | None = None  # full by default

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


# ---------------------------------------------------------------------------
# DoD test (a): core tools/list == the exact 14-set
# ---------------------------------------------------------------------------


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
        # BE-9017: health_check is step 1 of every rendered prompt — it MUST be in core.
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


# ---------------------------------------------------------------------------
# DoD test (c): full-profile tools/list byte-identical to the current 48
# (roster-lock parallel — full == the entire registered TOOL_SCOPES surface).
# ---------------------------------------------------------------------------


class TestFullProfileByteIdentity:
    @pytest.mark.asyncio
    async def test_full_profile_advertises_the_entire_surface(self, profile_mcp_client):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES

        new_client, holder = profile_mcp_client
        holder.profile_toolset = None  # full == no restriction

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert advertised == set(TOOL_SCOPES.keys()), (
            f"full profile is not byte-identical: missing {set(TOOL_SCOPES.keys()) - advertised}, "
            f"extra {advertised - set(TOOL_SCOPES.keys())}"
        )

    @pytest.mark.asyncio
    async def test_full_profile_can_dispatch_an_implement_gate_tool(self, profile_mcp_client):
        """A full session must NOT be profile-blocked from a tool its scope allows
        (WO-8003k: "never let a profile block a tool the auth scopes allow for a
        full session"). The call may still error downstream on missing state — what
        must NOT appear is the profile-rejection text."""
        new_client, holder = profile_mcp_client
        holder.profile_toolset = None  # full

        async with new_client() as session:
            result = await session.call_tool("launch_implementation", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" not in joined


# ---------------------------------------------------------------------------
# DoD test (b): an out-of-profile tools/call is rejected by the dispatch gate
# (the same defense-in-depth the scope gate provides).
# ---------------------------------------------------------------------------


class TestOutOfProfileDispatchRejected:
    @pytest.mark.asyncio
    async def test_core_profile_rejects_out_of_profile_call(self, profile_mcp_client):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _CORE_PROFILE_TOOLS

        async with new_client() as session:
            # spawn_job is NOT in core -> must be rejected even though the API-key
            # scope bypass would otherwise allow it.
            result = await session.call_tool(
                "spawn_job", {"project_id": str(uuid4()), "agent_name": "implementer", "mission": "probe"}
            )

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" in joined

    @pytest.mark.asyncio
    @pytest.mark.parametrize("gate_tool", _IMPLEMENT_GATE_TOOLS)
    async def test_standard_profile_rejects_implement_gate_tools(self, profile_mcp_client, gate_tool):
        """DoD #3 security bonus: a standard-profile session cannot call the
        implement-gate tools — server-enforced, not advisory."""
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _STANDARD_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool(gate_tool, {"project_id": str(uuid4())})

        assert result.is_error is True
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" in joined


# ---------------------------------------------------------------------------
# DoD test (d) + precedence: the profile resolver (pure, no transport).
# ---------------------------------------------------------------------------


class TestProfileResolverPrecedence:
    def test_api_key_default_is_full(self):
        """DoD #4: API-key default = full -> today's behavior unchanged for every
        existing CLI user (None == no profile restriction)."""
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "api_key"}) is None

    def test_jwt_without_scopes_is_standard(self):
        """BE-9017: a scope-less jwt (no mcp:agent) still defaults to standard —
        unchanged from before. Only mcp:agent-scoped sessions widen."""
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "jwt"}) == _STANDARD_PROFILE_TOOLS

    def test_jwt_with_scopes_but_no_agent_is_standard(self):
        """BE-9017: a jwt carrying read/write but NOT mcp:agent → standard (unchanged).
        The (k) security posture for non-agent OAuth sessions is untouched."""
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write"]}
        assert _profile_toolset_from_state(state) == _STANDARD_PROFILE_TOOLS

    def test_jwt_with_mcp_agent_is_orchestrator(self):
        """BE-9017 core fix: a jwt/OAuth session carrying mcp:agent (Desktop /
        connector / OAuth CLI default scope) → orchestrator, NOT standard. This is
        what unblocks the human-ferried orchestrator flow at staging step 2."""
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]}
        assert _profile_toolset_from_state(state) == _ORCHESTRATOR_PROFILE_TOOLS

    def test_jwt_with_mcp_agent_as_space_string_is_orchestrator(self):
        """BE-9017: the resolver tolerates a space-delimited scope string too, not
        just a list — a future auth path can't silently break the membership check."""
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS, _profile_toolset_from_state

        state = {"auth_method": "jwt", "scopes": "mcp:read mcp:write mcp:agent"}
        assert _profile_toolset_from_state(state) == _ORCHESTRATOR_PROFILE_TOOLS

    def test_api_key_with_mcp_agent_is_still_full(self):
        """BE-9017 second-order: the scope check only fires for jwt. An API-key
        session stays full regardless of scopes (today's CLI behavior unchanged)."""
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({"auth_method": "api_key", "scopes": ["mcp:agent"]}) is None

    def test_absent_auth_signal_fails_closed_to_empty(self):
        # SEC-9126: an absent auth signal now resolves to the fail-CLOSED empty
        # allow-set (advertise nothing, dispatch nothing), NOT the former
        # fail-open `full` (None). api_key/jwt are the only recognized signals.
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({}) == frozenset()

    def test_declared_profile_wins_over_auth_default(self):
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _profile_toolset_from_state

        # A jwt session (default standard) that DECLARES core -> core wins.
        state = {"auth_method": "jwt", "tool_profile": "core"}
        assert _profile_toolset_from_state(state) == _CORE_PROFILE_TOOLS

    def test_declared_full_widens_a_jwt_session(self):
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        # The operator widening path: a jwt session that declares full -> None.
        state = {"auth_method": "jwt", "tool_profile": "full"}
        assert _profile_toolset_from_state(state) is None

    def test_garbage_declared_profile_degrades_to_auth_default(self):
        # A garbage declared profile still degrades to the AUTH-DERIVED default
        # (WO-8003k DoD #2 — untouchable). SEC-9126 amendment 1: the auth default
        # is now fail-CLOSED for an unrecognized signal, so a garbage declaration
        # can never widen an unknown caller to the full surface.
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        # jwt (recognized) => standard, unchanged.
        assert _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "not_a_real_profile"}) == (
            _STANDARD_PROFILE_TOOLS
        )
        # unknown/absent auth signal => the fail-closed empty set (was full/None).
        assert _profile_toolset_from_state(
            {"auth_method": "future-auth-path", "tool_profile": "not_a_real_profile"}
        ) == (frozenset())


# ---------------------------------------------------------------------------
# Profile-set integrity: every profile tool is a registered tool; core is the
# exact 14; standard is a superset of core that excludes the gate tools.
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# BE-9017: the orchestrator profile (jwt + mcp:agent default) + the MANDATORY
# transport-layer regression — the field bug was in the LIVE tools/list filter,
# so these drive the actual filtered list, not just set membership.
# ---------------------------------------------------------------------------

# The connector/human-ferried orchestrator flow needs these visible at staging
# step 2 — their absence (health_check + get_staging_instructions + spawn_job) is
# exactly what the Desktop OAuth field test caught.
_ORCHESTRATOR_MUST_SEE = (
    "health_check",
    "get_staging_instructions",
    "spawn_job",
    "update_project_mission",
    "stage_project",
    "implement_project",  # kept IN: read-only + already gate-gated (BE-9017 fork)
)


class TestOrchestratorProfileSet:
    def test_orchestrator_is_full_minus_launch_implementation_only(self):
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES
        from api.endpoints.mcp_tools._base import _LAUNCH_GATE_TOOLS, _ORCHESTRATOR_PROFILE_TOOLS

        assert frozenset({"launch_implementation"}) == _LAUNCH_GATE_TOOLS
        assert frozenset(TOOL_SCOPES) - _LAUNCH_GATE_TOOLS == _ORCHESTRATOR_PROFILE_TOOLS
        # launch_implementation (the ONLY human-gate writer) is out; the two prep/
        # read tools stay in (fork decision — they cannot flip the gate).
        assert "launch_implementation" not in _ORCHESTRATOR_PROFILE_TOOLS
        assert "stage_project" in _ORCHESTRATOR_PROFILE_TOOLS
        assert "implement_project" in _ORCHESTRATOR_PROFILE_TOOLS

    def test_orchestrator_is_registered_in_the_profiles_map(self):
        from api.endpoints.mcp_tools._base import (
            _ORCHESTRATOR_PROFILE_TOOLS,
            PROFILE_ORCHESTRATOR,
            TOOL_PROFILES,
        )

        assert TOOL_PROFILES[PROFILE_ORCHESTRATOR] == _ORCHESTRATOR_PROFILE_TOOLS

    def test_every_profile_contains_health_check(self):
        """Two-sided: health_check is reachable from EVERY profile (core/standard/
        orchestrator explicitly; full via the None no-restriction sentinel)."""
        from api.endpoints.mcp_tools._base import (
            PROFILE_CORE,
            PROFILE_FULL,
            PROFILE_ORCHESTRATOR,
            PROFILE_STANDARD,
            TOOL_PROFILES,
        )

        for name in (PROFILE_CORE, PROFILE_STANDARD, PROFILE_ORCHESTRATOR):
            assert "health_check" in TOOL_PROFILES[name], f"{name} missing health_check"
        # full == None (no restriction) so health_check is never filtered out.
        assert TOOL_PROFILES[PROFILE_FULL] is None


class TestOrchestratorProfileTransportRegression:
    """The load-bearing regression: through the REAL tools/list filter, assert the
    ACTUAL advertised set an orchestrator (jwt + mcp:agent) session receives — the
    filter was the failing layer, so set membership alone is not enough."""

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
        """Chain the resolver → the live filter: resolve the profile for a jwt +
        mcp:agent state, pin THAT exact result, and assert the actual list. Proves
        the scope→orchestrator mapping and the filter agree on the real surface."""
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
        """Defense-in-depth: even a crafted tools/call to launch_implementation is
        server-rejected for an orchestrator session (the gate stays sacred)."""
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
        """Two-sided: keeping stage_project IN means an orchestrator session is NOT
        profile-blocked from it (it may error downstream on missing state — what must
        NOT appear is the profile-rejection text). Guards the BE-9015 flow."""
        new_client, holder = profile_mcp_client
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS

        holder.profile_toolset = _ORCHESTRATOR_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool("stage_project", {"project_id": str(uuid4())})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" not in joined


# ---------------------------------------------------------------------------
# Declared-profile capture: the middleware stamps the (d) client_info hint onto
# ASGI state, at the layer that plumbing lives (no second declaration mechanism).
# ---------------------------------------------------------------------------


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


# ---------------------------------------------------------------------------
# EM gate ask (WO-8003k DONE review): ONE end-to-end proof of the DECLARED tier
# through the real middleware — initialize persists giljo_tool_profile via the
# INF-8003d client_info capture; the NEXT request loads the session row,
# _stamp_declared_profile stamps request state, and the resolver yields the
# exact core set. Closes the "proven by composition" seam with real wiring.
# ---------------------------------------------------------------------------
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
