# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from mcp.types import ToolAnnotations

from api.endpoints.mcp_sdk_server import mcp
from api.endpoints.mcp_tools._tool_annotations import sync_annotation_titles


class _StubTool:

    def __init__(self, name: str, title: str | None, annotations: ToolAnnotations | None):
        self.name = name
        self.title = title
        self.annotations = annotations


def _live_tools():
    return list(mcp._tool_manager.list_tools())


def test_every_registered_tool_has_a_non_empty_annotations_title():
    tools = _live_tools()
    assert tools, "expected the MCP registry to have registered tools"
    missing = sorted(t.name for t in tools if t.annotations is None or not t.annotations.title)
    assert not missing, f"tools missing annotations.title (portal flags these): {missing}"


def test_annotations_title_equals_the_canonical_tool_title():
    mismatches = [
        (t.name, t.title, None if t.annotations is None else t.annotations.title)
        for t in _live_tools()
        if t.annotations is None or t.annotations.title != t.title
    ]
    assert not mismatches, (
        f"annotations.title diverges from Tool.title for (name, title, annotations.title): {mismatches}"
    )


async def test_wire_tools_list_carries_both_titles():
    wire_tools = await mcp.list_tools()
    assert wire_tools, "expected the wire tools/list to be non-empty"
    bad = sorted(t.name for t in wire_tools if not t.title or t.annotations is None or t.annotations.title != t.title)
    assert not bad, f"wire tools/list entries without agreeing title/annotations.title: {bad}"


def test_sync_copies_the_canonical_title_into_the_annotation():
    tool = _StubTool("fake_tool", "Fake Tool", ToolAnnotations(read_only_hint=True, open_world_hint=False))
    sync_annotation_titles([tool])
    assert tool.annotations.title == "Fake Tool"
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
    tool = _StubTool("untitled_tool", "", ToolAnnotations(read_only_hint=True))
    with pytest.raises(ValueError, match="untitled_tool"):
        sync_annotation_titles([tool])


def test_sync_fails_loud_for_a_tool_with_no_annotations_block():
    tool = _StubTool("hintless_tool", "Hintless Tool", None)
    with pytest.raises(ValueError, match="hintless_tool"):
        sync_annotation_titles([tool])
