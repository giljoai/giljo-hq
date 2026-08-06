# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9251 anti-drift gate for @mcp.tool title/annotations.

Anthropic's Claude Connectors Directory and OpenAI's Apps SDK both require every
listed MCP tool to carry a ``title`` and an accurate ``readOnlyHint`` (OpenAI
also ``openWorldHint``). This suite asserts THROUGH the live FastMCP registry
(``mcp._tool_manager.list_tools()`` — the same transport-level surface
``test_be6042d_mcp_tool_registry_surface.py`` locks) that:

1. Every registered tool exposes a non-empty ``title`` and a non-None
   ``annotations`` block.
2. Every tool's live ``readOnlyHint`` AGREES with ``TOOL_SCOPES`` — the single
   source of truth ``_tool_hints()`` (api/endpoints/mcp_tools/_tool_annotations.py)
   derives it from — UNLESS the tool is named in the explicit, membership-locked
   ``_READ_SCOPED_BUT_MUTATING`` override set (BE-9251 audit finding F2):
   ``get_thread_history`` is read-SCOPED for auth (a read-token client must
   reach the common plain-read case) but its ``mark_read=true`` param performs a
   genuine write (inserts ``message_acknowledgments``, decrements the dashboard
   "Messages Waiting" badge, fires a WS broadcast) -- readOnlyHint is a BEHAVIOR
   hint, not an auth-scope mirror, so advertising True there would be a
   directory client trusting a lie and skipping its confirmation prompt. This
   is the anti-drift gate: a tool hand-set to the wrong hint outside that one
   documented exception (or a future tool wired without going through
   ``_tool_hints``) fails here rather than silently misrepresenting itself to a
   directory listing. The override set's membership is itself locked by a
   dedicated test so it cannot silently grow.
3. ``destructiveHint``/``openWorldHint`` are never left at the MCP-spec-default
   ``None`` for a mutating tool -- the spec default for an unset
   ``destructiveHint`` is ``True`` and for ``openWorldHint`` is ``True``, so an
   omitted hint is not "no opinion", it is the worst-case assumption. Every
   mutating (mcp:write / mcp:agent) tool here must carry an explicit
   ``destructiveHint`` (bool, not None) and every tool must carry an explicit
   ``openWorldHint=False`` (this registry never talks to a third-party service).

Note: universal liveness/heartbeat telemetry (the ``_call_tool`` posthook that
touches ``last_activity_at`` / auto-clears 'silent' status for ANY call
carrying a ``job_id``, including read tools) is deliberately OUT OF SCOPE for
readOnlyHint (BE-9251 audit finding F4) -- see the module docstring in
``_tool_annotations.py`` for the full reasoning. Not tested here because it is
explicitly not a behavior this suite is meant to gate.
"""

from __future__ import annotations

from api.endpoints.mcp_sdk_server import TOOL_SCOPES, mcp
from api.endpoints.mcp_tools._base import SCOPE_READ
from api.endpoints.mcp_tools._tool_annotations import _READ_SCOPED_BUT_MUTATING, _tool_hints


def _live_tools():
    return list(mcp._tool_manager.list_tools())


def test_every_registered_tool_has_a_title():
    tools = _live_tools()
    assert tools, "expected the FastMCP registry to have registered tools"
    missing = sorted(t.name for t in tools if not t.title)
    assert not missing, f"tools missing a title: {missing}"


def test_every_registered_tool_has_annotations():
    missing = sorted(t.name for t in _live_tools() if t.annotations is None)
    assert not missing, f"tools missing annotations entirely: {missing}"


def test_read_only_hint_agrees_with_tool_scopes():
    """Anti-drift gate: readOnlyHint must equal (TOOL_SCOPES[name] == mcp:read),
    EXCEPT for a name in the explicit ``_READ_SCOPED_BUT_MUTATING`` override set,
    which must show ``readOnlyHint=False`` regardless of its TOOL_SCOPES entry
    (BE-9251 audit F2 -- see the module docstring above and
    ``_tool_annotations.py`` for why the exception exists). This ENCODES the
    exception rather than bypassing it: every override-set member is asserted
    to diverge in exactly the expected direction; every other tool must still
    agree with TOOL_SCOPES exactly.

    Every registered tool must have a TOOL_SCOPES entry (enforced independently
    by SEC-9126's _assert_tool_scope_completeness() at server boot) -- this test
    additionally locks that the ADVERTISED readOnlyHint never diverges from it
    (modulo the one documented, membership-locked exception).
    """
    mismatches = []
    for tool in _live_tools():
        assert tool.name in TOOL_SCOPES, f"{tool.name} has no TOOL_SCOPES entry"
        if tool.name in _READ_SCOPED_BUT_MUTATING:
            expected_read_only = False
        else:
            expected_read_only = TOOL_SCOPES[tool.name] == SCOPE_READ
        actual = tool.annotations.readOnlyHint if tool.annotations else None
        if actual != expected_read_only:
            mismatches.append((tool.name, actual, expected_read_only))
    assert not mismatches, (
        f"readOnlyHint disagrees with TOOL_SCOPES (or its documented _READ_SCOPED_BUT_MUTATING "
        f"override) for: {mismatches}"
    )


def test_read_scoped_but_mutating_override_set_membership_is_locked():
    """The _READ_SCOPED_BUT_MUTATING override set must not silently grow.

    BE-9251 audit F2: a new entry here weakens the anti-drift gate above (it
    lets a tool's advertised readOnlyHint diverge from TOOL_SCOPES without the
    general-case check catching it), so adding one must force an edit to THIS
    test -- making it a deliberate, reviewed act, never a silent side effect of
    touching ``_tool_annotations.py``.
    """
    assert frozenset({"get_thread_history"}) == _READ_SCOPED_BUT_MUTATING


def test_mutating_tools_carry_an_explicit_destructive_hint():
    """A mutating (write/agent) tool must never leave destructiveHint at None.

    Per the MCP spec, an unset destructiveHint defaults to True (the worst-case
    assumption for a client deciding whether to prompt for confirmation) -- so
    every mutating tool here must carry an explicit bool, set via _tool_hints().
    """
    missing = sorted(
        t.name
        for t in _live_tools()
        if TOOL_SCOPES[t.name] != SCOPE_READ and (t.annotations is None or t.annotations.destructiveHint is None)
    )
    assert not missing, f"mutating tools with no explicit destructiveHint: {missing}"


def test_every_tool_declares_open_world_false():
    """Every Giljo HQ tool hits the local DB, never a third-party service.

    Per the MCP spec, an unset openWorldHint defaults to True -- so every tool
    here must carry an explicit openWorldHint=False (via _tool_hints()).
    """
    not_closed_world = sorted(
        t.name for t in _live_tools() if t.annotations is None or t.annotations.openWorldHint is not False
    )
    assert not not_closed_world, f"tools not declaring openWorldHint=False: {not_closed_world}"


def test_tool_hints_helper_derives_read_only_from_tool_scopes():
    """Unit-level check on _tool_hints() itself (not just the live registry).

    Picks one real mcp:read tool and one real mcp:write tool from TOOL_SCOPES so
    this test can never silently rot if the tool roster changes.
    """
    read_name = next(name for name, scope in TOOL_SCOPES.items() if scope == SCOPE_READ)
    write_name = next(name for name, scope in TOOL_SCOPES.items() if scope != SCOPE_READ)

    read_hints = _tool_hints(read_name)
    assert read_hints.readOnlyHint is True
    assert read_hints.destructiveHint is None  # not meaningful when readOnlyHint=True
    assert read_hints.openWorldHint is False

    write_hints = _tool_hints(write_name, destructive=True)
    assert write_hints.readOnlyHint is False
    assert write_hints.destructiveHint is True
    assert write_hints.openWorldHint is False


def test_tool_hints_helper_fails_loud_for_an_unmapped_tool_name():
    """A name absent from TOOL_SCOPES must raise, never silently default to False.

    Guards the KeyError-not-.get() choice in _tool_hints() -- a typo'd tool name
    passed to the helper must fail import-time / test-time, not advertise a wrong
    readOnlyHint at runtime.
    """
    try:
        _tool_hints("this_tool_name_does_not_exist_be9251")
    except KeyError:
        pass
    else:
        raise AssertionError("expected _tool_hints() to raise KeyError for an unmapped tool name")
