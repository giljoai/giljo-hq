# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""SEC-9423 -- the SEC-9126 fail-closed authorization invariant, pinned at the SDK level.

SEC-9126's scope gating is installed on the SDK server AFTER the server object is
built, so nothing about the module importing cleanly proves the gate is actually in
force: the boot assert only checks registry completeness, and the SEC-9126 step-1
tests reach the gate through an in-memory client session. If the SDK changed where
handlers are installed -- silently ignoring our installation, or moving the point --
the module would still import, the boot assert would still pass, and scope gating
would revert to unfiltered.

INF-9371 RE-POINT (SDK 2.0). This file was written against 1.x, where the gate was
installed by re-invoking ``mcp._mcp_server.list_tools()`` / ``.call_tool()`` to
overwrite entries in the lowlevel ``request_handlers`` dict. 2.0 deletes those
decorators and hardcodes MCPServer's own handlers into the lowlevel slots, so the
gate now rides the public ``MCPServer.middleware`` chain
(``mcp_sdk_server._scope_gate``). **The installation point moved; the invariant did
not.** These tests were re-pointed, not weakened and not deleted -- which is exactly
what the ``_SHAPE_MOVED`` message below instructs the next migrator to do.

This file pins the INVARIANT, not the mechanism, at three layers:

  1. ``TestOverwriteTookEffectAtTheDispatchTable`` -- the gate ACTUALLY INSTALLED on
     the SDK server object applies the filter/refusal. This is the assertion the
     surface lacked; it names the installation point, so a migration that moves it
     fails HERE, loudly, with instructions rather than a silent revert to fail-open.
  2. ``TestTheseAssertionsCanFail`` -- negative controls. With the gate absent from the
     chain (i.e. simulating an installation that never took effect) the same
     assertions must FLIP. Without these, layer 1 could pass for reasons unrelated to
     the gate and nobody would know (a test can only fail in the dimension it was
     pointed at). This is the SEC-9423 mutation probe made permanent: the file
     re-proves on every run that it is capable of going red.
  3. ``TestInvariantThroughTheRealDispatchPath`` -- shape-agnostic end-to-end. Reaches
     the gate the way a real client does and touches no SDK internals, so it survives a
     handler-registration shape change unchanged. This is the form INF-9371's DoD 2
     ("the fail-closed invariant is re-proven, not re-compiled") is measured against.

Layer 3 deliberately does NOT monkeypatch the scope/profile resolvers the way
``test_mcp_authz_fail_closed.py`` does: outside an HTTP request ``_request_from_context()``
already returns ``None``, so both resolvers naturally yield the no-restriction posture.
Asserting against the unpatched resolvers keeps the API-key-equivalent bypass path
honest -- the registry filter must hold with nothing stubbed out.

``TestBootAssertRejectsBothDirections`` closes a real gap in the existing coverage:
``_assert_tool_scope_completeness`` checks two directions and only ``missing``
(registered-but-unmapped) was asserted. ``orphaned`` (mapped-but-unregistered) is
covered here.

Zero behavior change -- test-only, no production edit, no introspection hook (the SDK
already exposes the installed handlers read-only).

Parallel-safe: the synthetic tool is added/removed in a fixture ``finally``, so the
roster-locked tool count is never left mutated for a co-scheduled test in the same
xdist worker. (1.x also had to refresh the SDK's ``_tool_cache`` on teardown because
an ungated list handler would cache the synthetic tool; 2.0 has no such cache, so that
step is gone rather than kept as cargo.) The negative controls restore the SAVED gate
object at its original chain position -- deliberate, so a control cannot re-install a
freshly-built gate mid-session and mask its own RED. ``TOOL_SCOPES`` is mutated only
through ``monkeypatch.setitem``. No DB writes
(the synthetic tool is a pure no-op and dispatch is refused before any tool body runs),
so no ``TransactionalTestContext``. No module-level mutable state.

Edition Scope: Both.
"""

from __future__ import annotations

import pytest
import pytest_asyncio

from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


# A distinctive name so a leak into another test is unmistakable.
_SYNTHETIC_TOOL_NAME = "sec9423_synthetic_unmapped_tool"
_MAPPED_BUT_UNREGISTERED = "sec9423_mapped_but_never_registered"

# The fail-closed rejection text returned by _dispatch_refusal_reason.
_REFUSAL_FRAGMENT = "no authorization scope mapping"

# The name of the middleware that carries the gate. Resolved by name rather than by
# identity so this file does not have to import the production callable to find it --
# what is asserted is that the INSTALLED chain contains it and that it works.
_GATE_NAME = "_scope_gate"

# Emitted when the SDK's handler-installation shape has moved. Spelled out because the
# next reader is a migration author deciding whether to re-point or delete this file.
_SHAPE_MOVED = (
    "SEC-9423: the MCP SDK no longer exposes the authorization gate at its known "
    "installation point, so SEC-9126's fail-closed gate can no longer be located. "
    "RE-POINT the resolver below at the new installation point -- do NOT delete or skip "
    "these tests, and do NOT assume the gate is still installed. The invariant they pin "
    "(a registered tool with no TOOL_SCOPES entry is never advertised and never "
    "dispatched) is unchanged by any SDK shape change. Detail: "
)


async def _synthetic_noop() -> dict:
    """A pure no-op tool with NO ``TOOL_SCOPES`` entry. Returns a dict; no DB touch."""
    return {"sec9423_synthetic": True}


class _Ctx:
    """The slice of the SDK's per-request context the gate reads.

    ``ServerRequestContext`` is a dataclass the SDK builds per message; the gate only
    touches ``method``, ``params`` and ``request``. Standing this up directly is what
    lets layer 1 invoke the INSTALLED gate object in isolation. ``request=None`` is the
    no-HTTP-request posture, i.e. the same unaided posture layer 3 exercises.
    """

    def __init__(self, method: str, params: dict | None = None):
        self.method = method
        self.params = params
        self.request = None


def _installed_gate():
    """Return the authorization middleware ACTUALLY installed on the SDK server.

    Reaching for the live chain entry -- rather than the module-level ``_scope_gate``
    function -- is the whole point: the module-level function exists whether or not the
    installation that puts it in the chain took effect.
    """
    from api.endpoints.mcp_sdk_server import mcp

    chain = getattr(mcp, "middleware", None)
    if chain is None:
        pytest.fail(f"{_SHAPE_MOVED}MCPServer exposes no `middleware` chain.")
    for entry in chain:
        if getattr(entry, "__name__", "") == _GATE_NAME:
            return entry
    installed = [getattr(e, "__name__", type(e).__name__) for e in chain]
    pytest.fail(f"{_SHAPE_MOVED}no `{_GATE_NAME}` in the installed middleware chain: {installed}.")


async def _unfiltered_list_result() -> dict:
    """What the SDK's own tools/list handler hands the middleware chain: a plain dict.

    INF-9371/F1: 2.0 middleware observes results as ``dict`` (declared as
    ``BaseModel | dict | None``), NOT as a typed ``ListToolsResult`` -- the exact
    detail that makes an ``isinstance``-based filter silently fail OPEN. The stand-in
    handler below therefore returns the dict shape, so layer 1 exercises the branch
    production actually takes.
    """
    from api.endpoints.mcp_sdk_server import mcp

    tools = await mcp.list_tools()
    return {"tools": [t.model_dump(by_alias=True, exclude_none=True) for t in tools]}


def _advertised(result) -> set[str]:
    return {tool["name"] for tool in result["tools"]}


def _error_text(result) -> str:
    return "\n".join(getattr(block, "text", "") for block in result.content)


@pytest_asyncio.fixture
async def unmapped_tool():
    """Register a synthetic tool that has NO ``TOOL_SCOPES`` entry, then remove it.

    Teardown also refreshes the SDK's ``_tool_cache`` through the installed list
    handler: the negative-control tests deliberately run an ungated list handler, which
    caches the synthetic tool, and the cache must not outlive the tool itself.
    """
    from api.endpoints.mcp_sdk_server import mcp

    mcp._tool_manager.add_tool(_synthetic_noop, name=_SYNTHETIC_TOOL_NAME)
    try:
        yield _SYNTHETIC_TOOL_NAME
    finally:
        mcp._tool_manager.remove_tool(_SYNTHETIC_TOOL_NAME)


# ---------------------------------------------------------------------------
# Layer 1 -- the overwrite took effect on the SDK server object
# ---------------------------------------------------------------------------


class TestOverwriteTookEffectAtTheDispatchTable:
    @pytest.mark.asyncio
    async def test_installed_list_handler_applies_the_fail_closed_filter(self, unmapped_tool):
        """The gate the SDK will actually run must drop a tool with no scope mapping.
        Fails if the installation was ignored, replaced, or never ran -- the exact
        silent revert SEC-9423 exists to catch."""
        result = await _installed_gate()(_Ctx("tools/list"), lambda _ctx: _unfiltered_list_result())

        advertised = _advertised(result)
        assert advertised, "the installed gate advertised nothing at all; the roster is empty"
        assert unmapped_tool not in advertised, (
            "the gate INSTALLED on the SDK server advertised a registered tool with no "
            "TOOL_SCOPES entry. SEC-9126's authorization gate is not in effect and "
            "tools/list has reverted to unfiltered."
        )

    @pytest.mark.asyncio
    async def test_installed_call_handler_applies_the_fail_closed_gate(self, unmapped_tool):
        """Same assertion on the dispatch half: the installed gate must refuse an
        unmapped tool rather than let it reach the handler.

        The stand-in ``call_next`` records whether it was reached, so this asserts
        NON-EXECUTION directly rather than inferring it from an error flag.
        """
        reached = False

        async def call_next(_ctx):
            nonlocal reached
            reached = True
            return {}

        result = await _installed_gate()(_Ctx("tools/call", {"name": unmapped_tool, "arguments": {}}), call_next)

        assert not reached, (
            "the gate INSTALLED on the SDK server passed a registered tool with no "
            "TOOL_SCOPES entry through to the handler. SEC-9126's authorization gate is "
            "not in effect and tools/call has reverted to ungated."
        )
        assert result.is_error, "the refusal must carry is_error, i.e. the 1.28.1 wire shape"
        assert _REFUSAL_FRAGMENT in _error_text(result)

    @pytest.mark.asyncio
    async def test_unregistered_name_still_gets_the_sdk_error(self, unmapped_tool):
        """Overshoot guard: the fail-closed gate must fire only for registered-but-
        unmapped names. A name that was never registered is passed through to the SDK's
        own error path, so the gate cannot be credited for a rejection it did not make."""
        reached = False

        async def call_next(_ctx):
            nonlocal reached
            reached = True
            return {}

        await _installed_gate()(
            _Ctx("tools/call", {"name": "sec9423_never_registered_zzz", "arguments": {}}), call_next
        )

        assert reached, "an unregistered name must fall through to the SDK, not be claimed by the gate"


# ---------------------------------------------------------------------------
# Layer 2 -- negative controls: prove the layer-1 assertions can fail
# ---------------------------------------------------------------------------


class TestTheseAssertionsCanFail:
    """The SEC-9423 mutation probe, kept as standing tests.

    Each control removes the gate from the installed chain -- i.e. simulates the
    installation never having happened -- and asserts the protection is ABSENT, through
    the REAL dispatch path. A control that goes green under a real fail-open regression
    would mean layer 1 is watching the wrong dimension; a control that FAILS means the
    simulation itself is broken and layer 1's green must not be trusted until it is
    explained.
    """

    @staticmethod
    def _remove_gate():
        """Pull the gate out of the installed chain; returns a restore callable.

        The SAVED object is put back at its original index, so a control can never
        re-install a freshly-built gate and mask its own RED.
        """
        from api.endpoints.mcp_sdk_server import mcp

        gate = _installed_gate()
        index = mcp.middleware.index(gate)
        mcp.middleware.remove(gate)
        return lambda: mcp.middleware.insert(index, gate)

    @pytest.mark.asyncio
    async def test_sdk_default_list_handler_would_advertise_the_unmapped_tool(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        restore = self._remove_gate()
        try:
            async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
                result = await session.list_tools()
            assert unmapped_tool in {tool.name for tool in result.tools}, (
                "negative control did not reproduce the fail-open posture: the ungated "
                "server filtered the unmapped tool anyway. Suspect this control, not the "
                "production gate -- until it is explained, the layer-1 pass above proves nothing."
            )
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_sdk_default_call_handler_would_execute_the_unmapped_tool(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        restore = self._remove_gate()
        try:
            async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
                result = await session.call_tool(unmapped_tool, {})
            assert not result.is_error, (
                "negative control did not reproduce the fail-open posture: the ungated "
                "server refused the unmapped tool anyway. Suspect this control, not the "
                "production gate -- until it is explained, the layer-1 pass above proves nothing."
            )
        finally:
            restore()

    @pytest.mark.asyncio
    async def test_the_gate_is_restored_after_the_controls(self, unmapped_tool):
        """Guards the controls' own cleanup: whatever order the two tests above ran in,
        the gate must be back in the installed chain and filtering."""
        result = await _installed_gate()(_Ctx("tools/list"), lambda _ctx: _unfiltered_list_result())
        assert unmapped_tool not in _advertised(result), (
            "a negative control leaked an ungated server back into the middleware chain"
        )


# ---------------------------------------------------------------------------
# Layer 3 -- shape-agnostic: the invariant through the real dispatch path
# ---------------------------------------------------------------------------


class TestInvariantThroughTheRealDispatchPath:
    """Touches no SDK internals, so it holds across a handler-registration shape change.

    No resolver monkeypatching: with no HTTP request the scope and profile resolvers
    already return the no-restriction posture, which is the one the registry filter has
    to hold on unaided.
    """

    @pytest.mark.asyncio
    async def test_unmapped_tool_is_not_advertised(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
            result = await session.list_tools()

        assert unmapped_tool not in {tool.name for tool in result.tools}

    @pytest.mark.asyncio
    async def test_unmapped_tool_is_refused_at_dispatch(self, unmapped_tool):
        from api.endpoints import mcp_sdk_server

        async with create_connected_server_and_client_session(mcp_sdk_server.mcp) as session:
            result = await session.call_tool(unmapped_tool, {})

        assert result.is_error
        assert _REFUSAL_FRAGMENT in "\n".join(getattr(block, "text", "") for block in result.content)


# ---------------------------------------------------------------------------
# Boot assert -- both directions
# ---------------------------------------------------------------------------


class TestBootAssertRejectsBothDirections:
    def test_mapped_but_unregistered_tool_aborts_boot(self, monkeypatch):
        """The ``orphaned`` direction of ``_assert_tool_scope_completeness``: a scope
        entry naming a tool that is not registered must abort boot. Previously
        unasserted -- only the ``missing`` direction was covered."""
        from api.endpoints import mcp_sdk_server
        from api.endpoints.mcp_tools import _base

        monkeypatch.setitem(_base.TOOL_SCOPES, _MAPPED_BUT_UNREGISTERED, _base.SCOPE_READ)

        with pytest.raises(RuntimeError, match=_MAPPED_BUT_UNREGISTERED):
            mcp_sdk_server._assert_tool_scope_completeness()

    def test_registered_but_unmapped_tool_aborts_boot(self, monkeypatch):
        """The ``missing`` direction, asserted here WITHOUT registering a tool: dropping
        a live tool's scope entry is the realistic regression (someone renames a tool and
        forgets the registry), and it exercises the same branch without touching the roster."""
        from api.endpoints import mcp_sdk_server
        from api.endpoints.mcp_tools import _base

        monkeypatch.delitem(_base.TOOL_SCOPES, "health_check")

        with pytest.raises(RuntimeError, match="health_check"):
            mcp_sdk_server._assert_tool_scope_completeness()

    def test_clean_registry_is_silent(self):
        """The guard must not cry wolf on the shipped roster."""
        from api.endpoints import mcp_sdk_server

        mcp_sdk_server._assert_tool_scope_completeness()
