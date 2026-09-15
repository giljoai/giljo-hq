# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import asyncio
import re
from pathlib import Path


_GUIDE = Path(__file__).resolve().parents[2] / "src" / "giljo_mcp" / "tools" / "giljo_guide.py"

_NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}

_ROSTER_CLAIM = re.compile(r"^(?P<count>[A-Za-z]+|\d+) tools\b[^\n]*:$", re.M)

_CITED_TOOL = re.compile(r"`([a-z_][a-z0-9_]*)\(")

_SECTION_BREAK = re.compile(r"^## ", re.M)


def _live_tool_names() -> set[str]:
    from api.endpoints.mcp_tools import mcp

    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def _claimed_count(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token.lower())


def _roster_claims(source: str) -> list[tuple[int, str, int, set[str]]]:
    live = _live_tool_names()
    out: list[tuple[int, str, int, set[str]]] = []
    for match in _ROSTER_CLAIM.finditer(source):
        claimed = _claimed_count(match.group("count"))
        if claimed is None:
            continue
        rest = source[match.end() :]
        stop = _SECTION_BREAK.search(rest)
        section = rest[: stop.start()] if stop else rest
        cited = {name for name in _CITED_TOOL.findall(section) if name in live}
        line_no = source[: match.start()].count("\n") + 1
        out.append((line_no, match.group(0), claimed, cited))
    return out


def test_the_guide_still_contains_a_countable_roster() -> None:
    claims = _roster_claims(_GUIDE.read_text(encoding="utf-8"))
    assert claims, (
        f"No roster count claim found in {_GUIDE.name}. Either the guide was reformatted "
        "out of the 'Eleven tools:' shape this guard matches -- in which case widen the "
        "pattern rather than deleting the test -- or the roster is gone entirely."
    )


def test_every_roster_count_matches_the_tools_it_lists() -> None:
    wrong: list[str] = []
    for line_no, claim, claimed, cited in _roster_claims(_GUIDE.read_text(encoding="utf-8")):
        if claimed != len(cited):
            wrong.append(
                f"  giljo_guide.py:{line_no}: {claim!r} claims {claimed}, "
                f"but the section names {len(cited)} registered tools: {sorted(cited)}"
            )

    assert not wrong, (
        "A roster in the routing guide miscounts the tools it lists:\n"
        + "\n".join(wrong)
        + "\n\nThis is what a rename leaves behind when it correctly removes the NAMES and "
        "not the sentence that counts them -- no stale identifier exists, so no name-based "
        "guard can see it. Fix the number to match the list; do not add a tool to match "
        "the number."
    )


def test_the_count_guard_can_actually_fire_and_spares_true_prose() -> None:
    assert _ROSTER_CLAIM.search("Eleven tools:"), "failed to match the roster-claim shape"
    assert not _ROSTER_CLAIM.search("## 7. complete_job -- one tool, three phases (the server decides):"), (
        "flagged a heading that merely mentions a count"
    )
    assert not _ROSTER_CLAIM.search("- **Clearing the gate -- two doors, one write.** Both resolve the same row:"), (
        "flagged a true mid-sentence count"
    )

    assert _claimed_count("Eleven") == 11
    assert _claimed_count("9") == 9
    assert _claimed_count("Drive") is None, "a non-number word must not read as a count"
