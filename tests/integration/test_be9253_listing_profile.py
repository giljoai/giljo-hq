# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9253 — the ``listing`` tool profile + its URL-query selection vehicle.

Two things are proven here, at the layers they live in:

1. **The roster.** ``listing`` is a bespoke 11-tool lens for the public
   marketplace connector — the loop a reviewer can complete end to end in one
   session with no agent fleet and no ``job_id``. Locked by NAME (never by
   count) through the REAL ``tools/list`` filter, and by a dispatch-gate
   rejection so a crafted ``tools/call`` on a hidden name fails too.

2. **The selection vehicle.** A query-string variant of the published connector
   URL (``/mcp?profile=listing``) resolves into the EXISTING
   ``state['tool_profile']`` slot that ``_profile_toolset_from_state`` already
   reads — no new resolver rung, no parallel filter. Its load-bearing security
   property is **narrow-only**: the resolved toolset is always a subset of what
   the session would have resolved to WITHOUT the query string, so the URL can
   never widen a session. ``?profile=full`` is therefore structurally refused.

This file mirrors ``test_be8003k_tool_profiles.py`` and reuses its
``profile_mcp_client`` fixture rather than forking a second harness. Parallel-safe:
no module-level mutable state, no DB writes outside the transactional fixtures.

Edition Scope: Both.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

# Reuse the in-memory MCP client harness rather than forking a second copy of it.
# pytest resolves fixtures by name in the test module's namespace, so importing
# it here is enough.
from tests.integration.test_be8003k_tool_profiles import profile_mcp_client  # noqa: F401


# The exact 11-tool marketplace-listing loop. Hardcoded here as the ROSTER LOCK,
# deliberately duplicated from source: a change to the listing profile must break
# this test on purpose, not slip through. Asserted as a NAME SET, never a count.
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


# ---------------------------------------------------------------------------
# (1) The roster — through the REAL tools/list filter.
# ---------------------------------------------------------------------------


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
        """The whole point of the lens: none of the agent-fleet primitives a lone
        reviewer cannot exercise are advertised."""
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _LISTING_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        for hidden in ("spawn_job", "stage_project", "implement_project", "launch_implementation", "start_chain_run"):
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
        """Scope minimization: the whole lens is mcp:read + mcp:write, so the
        listing surface never needs the privileged mcp:agent scope."""
        from api.endpoints.mcp_sdk_server import TOOL_SCOPES
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        used = {TOOL_SCOPES[name] for name in _LISTING_PROFILE_TOOLS}
        assert used == {"mcp:read", "mcp:write"}, f"listing uses unexpected scopes: {sorted(used)}"

    def test_listing_is_a_subset_of_orchestrator(self):
        """The connector's auth-derived default is orchestrator; listing being a
        subset of it is what makes the URL vehicle a pure narrowing for that
        session."""
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS, _ORCHESTRATOR_PROFILE_TOOLS

        assert _LISTING_PROFILE_TOOLS <= _ORCHESTRATOR_PROFILE_TOOLS


# ---------------------------------------------------------------------------
# (2) Dispatch gate — hidden is not the only control.
# ---------------------------------------------------------------------------


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
        """Two-sided: update_project is the tool absent from core AND standard that
        the listing lens exists to include. It must NOT be profile-blocked (it may
        still error downstream on a nonexistent project)."""
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS

        new_client, holder = profile_mcp_client
        holder.profile_toolset = _LISTING_PROFILE_TOOLS

        async with new_client() as session:
            result = await session.call_tool("update_project", {"project_id": str(uuid4()), "status": "active"})

        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "not available in this session's tool profile" not in joined


# ---------------------------------------------------------------------------
# (3) The URL vehicle — unit level on the stamper, every baseline.
# ---------------------------------------------------------------------------


def _stamp(query: str, state: dict) -> dict:
    """Run the URL-profile stamper over a synthetic ASGI scope; return the state."""
    from api.endpoints.mcp_sdk_server import _stamp_url_profile

    scope = {"query_string": query.encode("ascii"), "state": dict(state)}
    _stamp_url_profile(scope)
    return scope["state"]


class TestUrlProfileNarrowing:
    def test_connector_session_narrows_to_listing(self):
        """The intended path: a jwt/OAuth connector session (auth-derived
        orchestrator) carrying ?profile=listing resolves to the 11-tool lens."""
        from api.endpoints.mcp_tools._base import _LISTING_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=listing", {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]})
        assert state["tool_profile"] == "listing"
        assert _profile_toolset_from_state(state) == _LISTING_PROFILE_TOOLS

    def test_api_key_session_narrows_to_listing(self):
        """An api_key baseline is unrestricted (None), so every profile is a
        narrowing of it and the vehicle applies."""
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
    """THE security property. A URL-supplied profile may only ever narrow the
    session; it can never enlarge the toolset the auth/declared ladder resolved."""

    def test_profile_full_never_reaches_the_unrestricted_sentinel(self):
        """``?profile=full`` on a jwt session must NOT resolve to None (no
        restriction). Without the guard this query string is a self-widening
        bypass reachable by any authenticated caller."""
        from api.endpoints.mcp_tools._base import _ORCHESTRATOR_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=full", {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write", "mcp:agent"]})
        assert "tool_profile" not in state
        resolved = _profile_toolset_from_state(state)
        assert resolved is not None, "?profile=full widened a jwt session to the unrestricted surface"
        assert resolved == _ORCHESTRATOR_PROFILE_TOOLS

    def test_profile_full_cannot_widen_a_declared_core_session(self):
        """The sharpest case: a session already narrowed to core by its declared
        profile. ``?profile=full`` must leave it at core, not blow it open."""
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=full", {"auth_method": "jwt", "tool_profile": "core"})
        assert state["tool_profile"] == "core"
        assert _profile_toolset_from_state(state) == _CORE_PROFILE_TOOLS

    def test_listing_is_refused_when_it_would_widen_a_standard_session(self):
        """listing is NOT a subset of standard (it adds update_project), so a jwt
        session without mcp:agent must NOT be able to reach it via the URL. An
        allowlist of {listing} alone would have let this through — the guard is a
        real subset check."""
        from api.endpoints.mcp_tools._base import _STANDARD_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=listing", {"auth_method": "jwt", "scopes": ["mcp:read", "mcp:write"]})
        assert "tool_profile" not in state
        assert _profile_toolset_from_state(state) == _STANDARD_PROFILE_TOOLS

    def test_listing_is_refused_when_it_would_widen_a_declared_core_session(self):
        """listing is not a subset of core either (update_project + get_roadmap)."""
        from api.endpoints.mcp_tools._base import _CORE_PROFILE_TOOLS, _profile_toolset_from_state

        state = _stamp("profile=listing", {"auth_method": "jwt", "tool_profile": "core"})
        assert state["tool_profile"] == "core"
        assert _profile_toolset_from_state(state) == _CORE_PROFILE_TOOLS

    def test_url_vehicle_cannot_escape_the_fail_closed_floor(self):
        """An unrecognized auth signal resolves to the empty allow-set (SEC-9126).
        No query string may lift a caller off that floor."""
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        for query in ("profile=listing", "profile=full", "profile=core", "profile=orchestrator"):
            state = _stamp(query, {"auth_method": "future-auth-path"})
            assert "tool_profile" not in state, f"{query} escaped the fail-closed floor"
            assert _profile_toolset_from_state(state) == frozenset()

    def test_every_profile_name_is_narrow_only_from_every_baseline(self):
        """Exhaustive invariant sweep: for every TOOL_PROFILES name and every
        baseline the middleware can stamp, the post-stamp toolset is a SUBSET of
        the pre-stamp toolset."""
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
                    continue  # unrestricted baseline: every outcome is a narrowing
                assert after is not None, f"?profile={name} widened {baseline} to the unrestricted surface"
                assert after <= before, f"?profile={name} widened {baseline} by {sorted(after - before)}"


# ---------------------------------------------------------------------------
# (4) End-to-end: the query string survives the REAL middleware to the resolver.
# Mirrors TestDeclaredProfileEndToEnd — same probe app, same driving helper.
# ---------------------------------------------------------------------------


class TestUrlProfileEndToEnd:
    @staticmethod
    async def _drive(db_manager, monkeypatch, *, query_string: bytes, client_info: dict):
        """initialize + a follow-up tools/list through the real MCPAuthMiddleware.

        Returns the ASGI state the inner app saw on the SECOND request.
        """
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
        """The plumbing proof: ?profile=listing on the real ASGI scope reaches
        _profile_toolset_from_state and yields the exact 11-tool set."""
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
        """Byte-identity floor: with no query parameter the declared-profile
        round-trip behaves exactly as it did before this mechanism existed."""
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
        """Narrow-only, proven through the REAL middleware: a session that declared
        core and is then driven with ?profile=full stays at core. Without the guard
        the query string would overwrite the declaration and open the full surface."""
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


# ---------------------------------------------------------------------------
# (5) The pre-existing profiles are untouched by this change.
# ---------------------------------------------------------------------------


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
        # The declared-profile widening path (BE-8003k/BE-9084) is deliberate and
        # stays exactly as it was — this change adds a vehicle, it does not alter
        # that rung.
        assert _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "full"}) is None
