# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tool behavior-hint annotations (BE-9251) -- lives in its own sibling module (not
``_base.py``) to keep ``_base.py`` under its shrink-only file-size guardrail
budget.

Anthropic's Claude Connectors Directory and OpenAI's Apps SDK both require a
``title`` and an accurate ``readOnlyHint``/``destructiveHint`` (OpenAI also
``openWorldHint``) on every listed MCP tool. ``title`` is passed as its own
``@mcp.tool(title=...)`` kwarg on each wrapper (the MCP-spec canonical display
field, distinct from the legacy ``ToolAnnotations.title``); this module builds
the three behavior hints via a single helper, ``_tool_hints()``, that every
domain wrapper module imports directly (not through ``_base``, for the same
file-size reason).

BE-9251 audit finding (F4) -- universal liveness/heartbeat telemetry is
INTENTIONALLY OUT OF SCOPE for readOnlyHint: ``_call_tool``'s posthook
(``_base.py``, the ``should_run("mcp_posthooks", ...)`` block) touches
``last_activity_at`` and may auto-clear a 'silent' agent status for ANY tool
call that carries a ``job_id`` -- including read tools like ``get_context``.
This is NOT the tool's own semantic behavior; it is process-wide liveness
telemetry shared by every dispatch, load-bearing for silent-agent detection
(museum rule -- do not change it). A directory client's readOnlyHint is about
whether INVOKING THE TOOL changes the data the tool is about, not about
incidental server bookkeeping every call pays -- so a read tool legitimately
keeps ``readOnlyHint=True`` despite this posthook. Recorded here so a future
pass doesn't "fix" this into a behavior regression (e.g. widening the
override set below to cover it, or touching the posthook itself).
"""

from __future__ import annotations

from mcp.types import ToolAnnotations

from api.endpoints.mcp_tools._base import SCOPE_READ, TOOL_SCOPES


# BE-9251 audit finding (F2): tools that are read-SCOPED for authorization
# (TOOL_SCOPES: mcp:read -- a read-only-token client must be able to reach the
# common case) but expose an opt-in parameter that performs a genuine write.
# readOnlyHint is a BEHAVIOR hint ("can invoking this modify state?"), not an
# auth-scope mirror -- so for these names it legitimately DIVERGES from the
# TOOL_SCOPES-derived default. Consulted BEFORE the scope derivation below.
#
# get_thread_history: TOOL_SCOPES=mcp:read (the plain-read case must stay
# reachable by a read-token client), but mark_read=true inserts
# message_acknowledgments rows, decrements the dashboard "Messages Waiting"
# badge, and fires a WS broadcast -- a real write. Advertising True here would
# be a directory client trusting a lie and skipping its confirmation prompt.
#
# Membership is deliberately locked shut (asserted exactly by the regression
# test in tests/unit/test_be9251_mcp_tool_annotations.py) so a new entry
# forces a test edit + review, not a silent addition.
_READ_SCOPED_BUT_MUTATING: frozenset[str] = frozenset({"get_thread_history"})


def _tool_hints(name: str, *, destructive: bool = False, open_world: bool = False) -> ToolAnnotations:
    """Build a tool's behavior-hint annotations for the ``@mcp.tool(annotations=...)`` kwarg.

    ``readOnlyHint`` is DERIVED from ``TOOL_SCOPES`` for every name NOT in
    ``_READ_SCOPED_BUT_MUTATING`` -- never otherwise hand-set per tool -- so the
    advertised hint can never drift from the scope registry that already gates
    dispatch: ``mcp:read`` -> ``readOnlyHint=True``; ``mcp:write`` / ``mcp:agent``
    -> ``readOnlyHint=False``. A name IN the override set always gets
    ``readOnlyHint=False`` regardless of its TOOL_SCOPES entry (see the set's
    docstring above -- these tools are read-scoped for auth but have an opt-in
    write mode). ``TOOL_SCOPES[name]`` (not ``.get``) so an unmapped name fails
    loud at import time instead of silently defaulting to "not read-only". The
    regression test in ``tests/unit/test_be9251_mcp_tool_annotations.py``
    asserts every registered tool's live ``readOnlyHint`` agrees with this
    derivation, INCLUDING the override exception (and locks the override set's
    exact membership).

    ``destructiveHint`` (per MCP spec, default True, meaningful only when
    ``readOnlyHint=False``) is caller-supplied and omitted (``None``) for
    read-only tools (readOnlyHint=True, i.e. not in the override set either).
    The rule applied across this registry: reserved for a tool that can close a
    project (write_project_closeout), complete/close a job (complete_job,
    close_job), write a terminal completed/cancelled status through a general
    update tool (update_project, update_task), release the one-way
    implementation-launch gate (launch_implementation -- set once, never
    reset), or the documented CTX self-close side effect
    (get_staging_instructions) -- i.e. a genuine delete or terminal state-flip.
    Every other write (creates, additive appends, merge-writes of prose/config
    fields, reversible status transitions like blocked/idle/sleeping/resume/
    dismiss/staged, or an override-set tool's opt-in write that only appends/
    drains an idempotent cursor like get_thread_history's mark_read) is
    additive or idempotent and stays False.

    ``openWorldHint`` (per MCP spec, default True) is caller-supplied, default
    False here: every Giljo HQ tool talks to the local DB, never an
    external/third-party service.
    """
    scope = TOOL_SCOPES[name]  # fail loud for an unmapped name -- checked unconditionally, override or not
    read_only = name not in _READ_SCOPED_BUT_MUTATING and scope == SCOPE_READ
    # INF-9371: SDK 2.0 renamed these model fields to snake_case. The camelCase
    # spellings still work HERE, as construction aliases -- this call was not
    # broken by the upgrade. They are spelled as fields anyway, so the one place
    # that builds annotations does not depend on an alias the SDK is free to drop,
    # and matches how every reader now accesses them.
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=None if read_only else destructive,
        open_world_hint=open_world,
    )
