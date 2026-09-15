# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import re

from tests.helpers.retired_tool_names import RETIRED_TOOL_NAMES


RETIRED_PHRASES: dict[str, str] = {
    "the active product": (
        "`is_active` is shown/hidden (several at once) and an unscoped read resolves "
        "to the DEFAULT product (`is_default`). Say 'default product', or name the "
        "product_id the caller should pass."
    ),
}

TOOL_SURFACE_CHAR_CEILING = 60_000




def _live_surface() -> list[tuple[str, str, str]]:
    from api.endpoints.mcp_tools import mcp

    async def _read() -> list[tuple[str, str, str]]:
        out: list[tuple[str, str, str]] = []
        for tool in await mcp.list_tools():
            out.append((tool.name, "description", tool.description or ""))
            props = (tool.input_schema or {}).get("properties", {}) or {}
            for param, spec in props.items():
                out.append((tool.name, f"param:{param}", spec.get("description", "") or ""))
        return out

    return asyncio.run(_read())


def test_no_retired_vocabulary_on_the_registered_surface() -> None:
    surface = _live_surface()
    hits: list[str] = []
    for phrase, remedy in RETIRED_PHRASES.items():
        for tool_name, location, text in surface:
            if phrase in text.lower():
                hits.append(f"  {tool_name}.{location}: contains {phrase!r}\n      -> {remedy}")

    assert not hits, (
        "Retired vocabulary is back on the agent-facing tool surface:\n"
        + "\n".join(hits)
        + "\n\nThis guard exists because six surfaces kept saying 'the active product' for "
        "days after the resolver moved to is_default, and every one of them shipped green."
    )


def test_the_guard_can_actually_fire() -> None:
    fake_surface = [("some_tool", "param:product_id", "Omit to use the active product.")]
    hits = [t for _n, _l, t in fake_surface if "the active product" in t.lower()]
    assert hits, "The retired-phrase detection failed to match a known-bad string."


def test_tool_surface_stays_under_its_ceiling() -> None:
    total = sum(len(text) for _name, _loc, text in _live_surface())
    assert total <= TOOL_SURFACE_CHAR_CEILING, (
        f"The agent-facing tool surface is {total:,} chars, over the "
        f"{TOOL_SURFACE_CHAR_CEILING:,} ceiling by {total - TOOL_SURFACE_CHAR_CEILING:,}.\n"
        "Every character here is read by every agent on every call, including small "
        "models on constrained harnesses.\n"
        "If the growth is justified, raise TOOL_SURFACE_CHAR_CEILING in this file in the "
        "same commit and say in the PR body what bought the characters."
    )


def test_no_retired_tool_name_is_referenced_on_the_surface() -> None:
    live = {name for name, _loc, _text in _live_surface()}
    hits: list[str] = []
    for retired, replacement in RETIRED_TOOL_NAMES.items():
        if retired in live:
            continue
        pattern = re.compile(rf"\b{re.escape(retired)}\b")
        for tool_name, location, text in _live_surface():
            if pattern.search(text):
                hits.append(f"  {tool_name}.{location}: names retired tool {retired!r} -> use {replacement}")

    assert not hits, (
        "Retired tool names are referenced on the agent-facing surface:\n"
        + "\n".join(sorted(set(hits)))
        + "\n\nAn agent reading this looks for a tool that is not on its list. If you are "
        "renaming a tool, grep the whole surface for the old name -- the registry entry is "
        "never the only place it appears."
    )


def test_the_retired_name_guard_can_actually_fire() -> None:
    pattern = re.compile(r"\bpass_baton\b")
    assert pattern.search("call pass_baton to hand off"), "word-boundary match failed on a real hit"
    assert not pattern.search("see the pass_baton_to parameter"), "matched a live parameter name"

    doc = re.compile(r"\bget_vision_doc\b")
    assert doc.search("call get_vision_doc first"), "word-boundary match failed on a real hit"
    assert not doc.search("call get_vision_document first"), "matched the live tool it is a prefix of"
