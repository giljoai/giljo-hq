# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9561 gate: every tool must advertise BOTH MCP title fields, and they must agree.

MCP carries two title fields on a tool: the modern, spec-canonical ``Tool.title``
(set via ``@mcp.tool(title=...)``) and the older ``ToolAnnotations.title``.
BE-9251 deliberately set only the first. Anthropic's connector submission portal
scans the SECOND, so it flagged all 49 tools with ``Missing annotations: title``
-- a clean-by-spec decision failing their checker on every tool.

The fix is a single post-registration pass (``sync_annotation_titles()`` in
``api/endpoints/mcp_tools/_tool_annotations.py``, called once from this
subpackage's ``__init__``), NOT a second title hand-maintained at 49 call sites.
Two titles typed in two places is a drift generator; copying one into the other
is structurally incapable of disagreeing.

This suite asserts through the live registry AND through the wire conversion
(``MCPServer.list_tools()``, what a directory client actually receives) that:

1. Every registered tool exposes a non-empty ``annotations.title``.
2. That annotation title EQUALS the canonical ``Tool.title`` -- the anti-drift
   pin, so a future edit cannot let the two fields say different things.
3. The pass itself never overwrites a title someone set explicitly, and is
   idempotent (re-running it is a no-op).

Deliberately NOT retested here: the ``readOnlyHint`` scope derivation, the
``_READ_SCOPED_BUT_MUTATING`` membership lock, and the destructive/openWorld
hints. Those are BE-9251's gate and stay owned by
``tests/unit/test_be9251_mcp_tool_annotations.py``.
"""

from __future__ import annotations

import pytest
from mcp.types import ToolAnnotations

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._tool_annotations import sync_annotation_titles


class _StubTool:
    """Minimal stand-in for a registered tool, so the pass can be unit-tested
    without mutating the process-wide registry (xdist-parallel-safe)."""

    def __init__(self, name: str, title: str | None, annotations: ToolAnnotations | None):
        self.name = name
        self.title = title
        self.annotations = annotations


def _live_tools():
    return list(mcp._tool_manager.list_tools())


def test_every_registered_tool_has_a_non_empty_annotations_title():
    """The submission-portal check: ``annotations.title`` must be set on every tool."""
    tools = _live_tools()
    assert tools, "expected the MCP registry to have registered tools"
    missing = sorted(t.name for t in tools if t.annotations is None or not t.annotations.title)
    assert not missing, f"tools missing annotations.title (portal flags these): {missing}"


def test_annotations_title_equals_the_canonical_tool_title():
    """Anti-drift pin: the two MCP title fields must never say different things."""
    mismatches = [
        (t.name, t.title, None if t.annotations is None else t.annotations.title)
        for t in _live_tools()
        if t.annotations is None or t.annotations.title != t.title
    ]
    assert not mismatches, (
        f"annotations.title diverges from Tool.title for (name, title, annotations.title): {mismatches}"
    )


async def test_wire_tools_list_carries_both_titles():
    """Assert on the WIRE surface a directory client actually receives.

    ``MCPServer.list_tools()`` builds each ``mcp.types.Tool`` from the registered
    tool, passing ``annotations`` through by reference -- so this is the same
    object the post-registration pass touched, seen the way the portal sees it.
    """
    wire_tools = await mcp.list_tools()
    assert wire_tools, "expected the wire tools/list to be non-empty"
    bad = sorted(t.name for t in wire_tools if not t.title or t.annotations is None or t.annotations.title != t.title)
    assert not bad, f"wire tools/list entries without agreeing title/annotations.title: {bad}"


def test_sync_copies_the_canonical_title_into_the_annotation():
    tool = _StubTool("fake_tool", "Fake Tool", ToolAnnotations(read_only_hint=True, open_world_hint=False))
    sync_annotation_titles([tool])
    assert tool.annotations.title == "Fake Tool"
    # The hints it did not own must survive untouched.
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False


def test_sync_is_idempotent():
    tool = _StubTool("fake_tool", "Fake Tool", ToolAnnotations(read_only_hint=True))
    sync_annotation_titles([tool])
    sync_annotation_titles([tool])
    assert tool.annotations.title == "Fake Tool"


def test_sync_never_overwrites_an_explicitly_set_annotation_title():
    tool = _StubTool("fake_tool", "Canonical", ToolAnnotations(title="Deliberate Override", read_only_hint=True))
    sync_annotation_titles([tool])
    assert tool.annotations.title == "Deliberate Override"


def test_sync_fails_loud_for_a_tool_with_no_canonical_title():
    """A titleless tool is a directory-submission defect -- it must not sync silently."""
    tool = _StubTool("untitled_tool", "", ToolAnnotations(read_only_hint=True))
    with pytest.raises(ValueError, match="untitled_tool"):
        sync_annotation_titles([tool])


def test_sync_fails_loud_for_a_tool_with_no_annotations_block():
    """No annotations block means the tool skipped ``_tool_hints()`` entirely."""
    tool = _StubTool("hintless_tool", "Hintless Tool", None)
    with pytest.raises(ValueError, match="hintless_tool"):
        sync_annotation_titles([tool])
