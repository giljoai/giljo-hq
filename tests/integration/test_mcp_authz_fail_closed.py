# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9126 -- fail-closed MCP tool authorization (enforcement-first, Step 1).

Museum rule: these tests are authored BEFORE the production change and are
observed RED for the predicted reasons (tests 1, 2, 4, 6 -- test 6 via a lazy
in-body attribute lookup raising AttributeError, NOT a collection error). The
captured fail-first output is recorded in the PR body before the production diff.

Two layers, matching where each defect lives:
  - Layer A (MCP transport boundary): a registered-but-unmapped tool must be
    neither advertised nor dispatchable on ANY auth path -- the reproduction of
    F1 (the scopes-None / profile-None API-key-bypass posture skips both axes,
    so an unmapped tool executes today with zero authorization check).
  - Layer B (resolver unit): an unknown/absent auth signal must resolve to the
    most-restrictive empty allow-set, not ``full`` -- the reproduction of F2;
    plus the startup completeness assert (the enforced single source of truth).

Parallel-safe: the synthetic unmapped tool registers/deregisters inside a
fixture (Layer A) or a try/finally (test 6), so the 44-tool roster is never left
mutated for a co-scheduled test in the same xdist worker. No DB writes (the
synthetic tool is a pure no-op), so no TransactionalTestContext. monkeypatch
only, no module-level mutable state. Edition Scope: Both.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


# A distinctive name so a leak is unmistakable and the RuntimeError match is exact.
_SYNTHETIC_TOOL_NAME = "sec9126_synthetic_unmapped_tool"


async def _synthetic_noop() -> dict:
    """A pure no-op tool with NO ``TOOL_SCOPES`` entry. Returns a dict; no DB touch."""
    return {"sec9126_synthetic": True}


@pytest_asyncio.fixture
async def unmapped_tool_client(monkeypatch):
    """In-memory MCP client with a synthetic registered-but-unmapped tool.

    Mirrors ``test_be8003k_tool_profiles.py::profile_mcp_client``: monkeypatches
    the scope/profile resolvers on ``mcp_sdk_server`` to the API-key-bypass
    posture (``scopes`` None, ``profile`` None) so BOTH auth axes bypass -- the
    exact posture under which F1 fails open today. The synthetic tool is removed
    from ``mcp._tool_manager`` in ``finally`` (the roster test asserts exactly 44
    tools; leaking it breaks unrelated tests in the same xdist worker).
    """
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base

    class _Holder:
        scopes: set[str] | None = None  # API-key bypass
        profile_toolset: frozenset[str] | None = None  # full / no restriction

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


# ---------------------------------------------------------------------------
# Layer A -- MCP transport boundary (F1)
# ---------------------------------------------------------------------------


class TestLayerAUnmappedToolUnreachable:
    @pytest.mark.asyncio
    async def test_unmapped_registered_tool_is_not_dispatchable_on_any_auth_path(self, unmapped_tool_client):
        """F1 reproduction: on the scopes-None / profile-None (API-key) posture the
        gate skips both axes today and the unmapped tool EXECUTES. After the fix a
        registry-membership gate must reject it with the fail-closed message."""
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
        """Same posture: the unmapped tool must be filtered out of tools/list even
        for a scopes-None / profile-None session (unconditional registry filter)."""
        new_client, holder = unmapped_tool_client
        holder.scopes = None
        holder.profile_toolset = None

        async with new_client() as session:
            result = await session.list_tools()

        advertised = {t.name for t in result.tools}
        assert _SYNTHETIC_TOOL_NAME not in advertised

    @pytest.mark.asyncio
    async def test_unregistered_tool_name_keeps_sdk_error(self, unmapped_tool_client):
        """The new gate must fire ONLY for registered-but-unmapped names. A name
        that is not registered at all must still surface the SDK's native
        unknown-tool error, never the new fail-closed rejection."""
        new_client, holder = unmapped_tool_client
        holder.scopes = None
        holder.profile_toolset = None

        async with new_client() as session:
            result = await session.call_tool("sec9126_never_registered_zzz", {})

        assert result.is_error
        joined = "\n".join(getattr(b, "text", "") for b in result.content)
        assert "no authorization scope mapping" not in joined


# ---------------------------------------------------------------------------
# Layer B -- resolver unit (F2) + startup completeness assert
# ---------------------------------------------------------------------------


class TestLayerBResolverFailClosed:
    def test_unknown_auth_signal_resolves_to_empty_allow_set(self):
        """F2 reproduction: an absent auth signal, and any unrecognized
        ``auth_method`` the middleware never stamps today, must resolve to the
        most-restrictive empty allow-set (advertise nothing, dispatch nothing) --
        not ``full`` (None). Fails today (returns None)."""
        from api.endpoints.mcp_tools._base import _profile_toolset_from_state

        assert _profile_toolset_from_state({}) == frozenset()
        assert _profile_toolset_from_state({"auth_method": "future-auth-path"}) == frozenset()

    def test_overshoot_guards_recognized_signals_unchanged(self):
        """Every RECOGNIZED signal keeps its exact behavior before AND after the
        flip -- the fail-closed floor must not overshoot into a legitimate path."""
        from api.endpoints.mcp_tools._base import (
            _CORE_PROFILE_TOOLS,
            _ORCHESTRATOR_PROFILE_TOOLS,
            _STANDARD_PROFILE_TOOLS,
            _profile_toolset_from_state,
        )

        # api_key => full (None): today's CLI behavior, byte-identical.
        assert _profile_toolset_from_state({"auth_method": "api_key"}) is None
        # jwt (no mcp:agent) => standard.
        assert _profile_toolset_from_state({"auth_method": "jwt"}) == _STANDARD_PROFILE_TOOLS
        # jwt + mcp:agent => orchestrator.
        assert (
            _profile_toolset_from_state({"auth_method": "jwt", "scopes": ["mcp:agent"]}) == _ORCHESTRATOR_PROFILE_TOOLS
        )
        # A declared known profile still wins over the auth default.
        assert _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "core"}) == _CORE_PROFILE_TOOLS
        # A garbage declared profile still degrades to the auth default (jwt => standard).
        assert (
            _profile_toolset_from_state({"auth_method": "jwt", "tool_profile": "not_a_real_profile"})
            == _STANDARD_PROFILE_TOOLS
        )

    def test_startup_completeness_assert_raises_on_unmapped_tool(self):
        """The Step-2c ``_assert_tool_scope_completeness()`` raises RuntimeError
        naming a registered-but-unmapped tool, and returns silently on a clean
        registry.

        Resolved LAZILY inside the test body (attribute access on the
        already-imported module): before Step 2c this raises AttributeError --
        the ONLY pre-2c failure of this test (NOT a collection error), so the
        predicted RED of tests 1, 2, 4 above is never masked by a module-level
        import of a not-yet-existing symbol."""
        from api.endpoints import mcp_sdk_server

        fn = mcp_sdk_server._assert_tool_scope_completeness

        # Clean 44-tool registry => silent (no raise).
        fn()

        mcp_sdk_server.mcp._tool_manager.add_tool(_synthetic_noop, name=_SYNTHETIC_TOOL_NAME)
        try:
            with pytest.raises(RuntimeError, match=_SYNTHETIC_TOOL_NAME):
                fn()
        finally:
            mcp_sdk_server.mcp._tool_manager.remove_tool(_SYNTHETIC_TOOL_NAME)
