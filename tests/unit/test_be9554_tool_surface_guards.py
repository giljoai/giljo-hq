# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9554 item 7 -- the two guards that make this pass stick.

Every false instruction the phase-1 audit found was introduced by a project that
shipped GREEN, in the four days before the audit. Each of those lanes changed
behaviour correctly, pinned it red-first, and left a tool description behind
describing the old world. Applying CLAUDE.md's mechanism-vs-prose test: a careful
lane can do everything right and still ship a description that lies, because
nothing checks the prose. That is a mechanism gap, and prose cannot close it.

Two guards, neither of which changes behaviour:

1. VOCABULARY -- "the active product" is provably wrong today. `is_active` means
   shown/hidden, and where an unscoped read resolves is `is_default`. The phrase
   was found on six surfaces long after the resolver moved. This asserts it is
   gone and stays gone. Extend the retired list as other concepts are settled.

2. BUDGET -- the measured surface moved 24.6k -> 26.2k in two days with nobody
   noticing, because nobody was counting. A ratcheted ceiling makes growth a
   deliberate act: adding prose is fine, adding it silently is not. Same shape as
   scripts/function_length_budgets.txt, and the same reason it works there.

The ceiling is deliberately set with headroom ABOVE the current measurement, not
flush against it -- a budget with no slack punishes the next lane for a legitimate
sentence and teaches everyone to raise the number reflexively, which is how a
ratchet stops meaning anything.
"""

from __future__ import annotations

import asyncio
import re

from tests.helpers.retired_tool_names import RETIRED_TOOL_NAMES


# Retired vocabulary: phrases that describe a world the code left behind. A hit
# here is a stale description, not a style opinion.
RETIRED_PHRASES: dict[str, str] = {
    "the active product": (
        "`is_active` is shown/hidden (several at once) and an unscoped read resolves "
        "to the DEFAULT product (`is_default`). Say 'default product', or name the "
        "product_id the caller should pass."
    ),
}

# Ratcheted ceiling on the whole agent-facing schema surface (descriptions +
# parameter descriptions, summed across every registered tool).
#
# HOW TO CHANGE THIS NUMBER: if your change genuinely needs more surface -- new
# parameters that need documenting, a tool that must explain a real gate -- raise
# it in the SAME commit, and say in the PR body what bought the characters. That
# is the whole point: the number moving is fine, the number moving unnoticed is not.
TOOL_SURFACE_CHAR_CEILING = 60_000


# Tool names this pass removed, mapped to what a caller should reach for instead.
# A description naming one of these sends a small model looking for a tool that is
# not on its list -- the same failure as a description that lies about behaviour,
# except the model cannot even attempt the call.
#
# Matched on WORD BOUNDARIES, which is load-bearing: `pass_baton_to` is a live
# PARAMETER on post_to_thread and `get_vision_document` is a live TOOL, and a naive
# substring scan flags both. A guard that cries wolf gets deleted by the next lane.
#
# BE-9563: the map moved to tests/helpers/retired_tool_names.py, shared with the
# prompt-prose guard. It used to be defined HERE, and PR #1013's rename sweep
# rewrote its keys to the NEW names -- which the `if retired in live: continue`
# line below then skipped, so this guard checked nothing for a release. One list
# now, and test_be9563_prompt_tool_names.py asserts every key is genuinely absent
# from the registry, so the next sweep fails loudly instead of going quiet.


def _live_surface() -> list[tuple[str, str, str]]:
    """Every agent-readable string on the registered surface.

    Returns (tool_name, location, text) so a failure names the exact place to fix
    rather than making the reader grep for it.
    """
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
    """A phrase describing behaviour the code no longer has is a false instruction,
    and a small model reading only the description has no way to know better."""
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
    """Checker-must-fire, inline: prove the detection works rather than trusting that
    an empty result means clean. A guard that cannot fail is not a guard."""
    fake_surface = [("some_tool", "param:product_id", "Omit to use the active product.")]
    hits = [t for _n, _l, t in fake_surface if "the active product" in t.lower()]
    assert hits, "The retired-phrase detection failed to match a known-bad string."


def test_tool_surface_stays_under_its_ceiling() -> None:
    """Growth is allowed; silent growth is not."""
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
    """The cross-reference half of the vocabulary guard.

    Renaming a tool updates the registry entry; it does not update the OTHER tools
    that mention it in prose. Four descriptions survived this pass still pointing at
    tools that had just been removed -- and every one of them read perfectly well,
    because a stale name is only detectable against the live roster. That is a
    mechanism gap by CLAUDE.md's test: no amount of care during a rename finds it.
    """
    live = {name for name, _loc, _text in _live_surface()}
    hits: list[str] = []
    for retired, replacement in RETIRED_TOOL_NAMES.items():
        if retired in live:
            continue  # the name came back as a real tool; nothing stale about it
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
    """Checker-must-fire, including the false-positive cases that would make this guard
    useless. `pass_baton_to` and `get_vision_document` must NOT match."""
    pattern = re.compile(r"\bpass_baton\b")
    assert pattern.search("call pass_baton to hand off"), "word-boundary match failed on a real hit"
    assert not pattern.search("see the pass_baton_to parameter"), "matched a live parameter name"

    doc = re.compile(r"\bget_vision_doc\b")
    assert doc.search("call get_vision_doc first"), "word-boundary match failed on a real hit"
    assert not doc.search("call get_vision_document first"), "matched the live tool it is a prefix of"
