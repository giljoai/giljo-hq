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

TOOL_SURFACE_CHAR_CEILING = 47_500




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


def _title_keys(schema: object, path: str = "") -> list[str]:
    hits: list[str] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key == "title" and isinstance(value, str):
                hits.append(f"{path}.title={value!r}")
            else:
                hits.extend(_title_keys(value, f"{path}.{key}"))
    elif isinstance(schema, list):
        for index, value in enumerate(schema):
            hits.extend(_title_keys(value, f"{path}[{index}]"))
    return hits


def test_input_schemas_carry_no_title_metadata() -> None:
    from api.endpoints.mcp_tools import mcp

    async def _schemas() -> list[tuple[str, dict]]:
        return [(tool.name, tool.input_schema or {}) for tool in await mcp.list_tools()]

    hits = [f"{name}{hit}" for name, schema in asyncio.run(_schemas()) for hit in _title_keys(schema)]
    assert not hits, "JSON-schema title metadata is back on the advertised surface:\n  " + "\n  ".join(hits[:20])


def test_the_title_guard_can_actually_fire_and_spares_a_parameter_named_title() -> None:
    schema = {
        "title": "create_taskArguments",
        "properties": {"title": {"type": "string", "title": "Title"}, "x": {"type": "integer"}},
        "$defs": {"_Nested": {"title": "_Nested", "properties": {}}},
    }
    hits = _title_keys(schema)
    assert len(hits) == 3, hits
    assert any("properties.title.title=" in h for h in hits), "the metadata INSIDE the title property must be found"
    assert not any(h.endswith(".properties.title") for h in hits), "the property named title must not be flagged"


def test_the_retired_name_guard_can_actually_fire() -> None:
    pattern = re.compile(r"\bpass_baton\b")
    assert pattern.search("call pass_baton to hand off"), "word-boundary match failed on a real hit"
    assert not pattern.search("see the pass_baton_to parameter"), "matched a live parameter name"

    doc = re.compile(r"\bget_vision_doc\b")
    assert doc.search("call get_vision_doc first"), "word-boundary match failed on a real hit"
    assert not doc.search("call get_vision_document first"), "matched the live tool it is a prefix of"
