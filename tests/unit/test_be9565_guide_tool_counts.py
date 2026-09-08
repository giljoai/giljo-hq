# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9565 -- a roster's stated COUNT must match the tools it actually lists.

BE-9554 merged three Hub tools away: ``await_my_turn`` into
``get_my_turn(wait_seconds=)``, ``search_threads`` into ``list_threads(query=)``,
and ``pass_baton`` into ``set_next_actor``. The routing guide's Hub section
correctly dropped all three names and gained ``set_next_actor`` -- eleven tools
became nine -- and the sentence introducing them still said **"Eleven tools:"**.
Live on prod, in ``get_giljo_guide``, which the guide itself tells every agent to
"call once, early, to become competent".

**This is a different defect class from BE-9563, and that is the whole point of
this file.** Every guard written for the rename sweep hunts IDENTIFIERS: the
retired-name denylist, the roster allowlists, the frontend scan. Not one of them
can see this, because there is no stale token to find -- the names are all
correct. A rename falsified a claim without leaving a single wrong identifier
behind. The lie is a CARDINALITY.

Three independent sweeps missed it (the server prose scan, the docs sweep, the
frontend scan), and it was found by making a live read-only call to the DEPLOYED
server and counting, rather than by re-reading source already believed clean.

WHAT THIS GUARD MATCHES, and why it is deliberately narrow. It fires only on a
line that BEGINS with a count and ENDS with a colon -- the shape that introduces
a roster (``Eleven tools:``). The guide contains two other cardinality phrases
that are true and must never be flagged:

    ## 7. complete_job -- one tool, three phases ...
    - **Clearing the gate -- two doors, one write.** ...

Neither begins with the count, so neither matches. A guard that cries wolf gets
deleted by the next lane, and these two would make it cry wolf on every run.

WHAT IT DOES NOT COVER, stated so nobody assumes otherwise: a count written
mid-sentence ("the Hub has eleven tools"), a count of something other than tools,
and any roster outside ``giljo_guide.py``. If a roster count appears in one of
those forms, widen this deliberately rather than assuming it is already watched.
``test_the_guide_still_contains_a_countable_roster`` is what stops the narrowness
from decaying into a vacuous pass: if the guide is reformatted so no claim matches
at all, this file fails instead of quietly checking nothing -- the failure mode
three pins demonstrated the night this was written.
"""

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

# A line that BEGINS with a count and ENDS with a colon: the roster-introducing form.
_ROSTER_CLAIM = re.compile(r"^(?P<count>[A-Za-z]+|\d+) tools\b[^\n]*:$", re.M)

# A backticked call in the guide's prose: `create_thread(...)`.
_CITED_TOOL = re.compile(r"`([a-z_][a-z0-9_]*)\(")

# Sections are markdown H2s.
_SECTION_BREAK = re.compile(r"^## ", re.M)


def _live_tool_names() -> set[str]:
    from api.endpoints.mcp_tools import mcp

    return {tool.name for tool in asyncio.run(mcp.list_tools())}


def _claimed_count(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return _NUMBER_WORDS.get(token.lower())


def _roster_claims(source: str) -> list[tuple[int, str, int, set[str]]]:
    """Every roster-introducing count claim, with the tools its section cites.

    Returns (line_number, claim_text, claimed_count, cited_live_tool_names).
    """
    live = _live_tool_names()
    out: list[tuple[int, str, int, set[str]]] = []
    for match in _ROSTER_CLAIM.finditer(source):
        claimed = _claimed_count(match.group("count"))
        if claimed is None:
            continue  # not a number -- e.g. "Drive it with these tools:"
        rest = source[match.end() :]
        stop = _SECTION_BREAK.search(rest)
        section = rest[: stop.start()] if stop else rest
        cited = {name for name in _CITED_TOOL.findall(section) if name in live}
        line_no = source[: match.start()].count("\n") + 1
        out.append((line_no, match.group(0), claimed, cited))
    return out


def test_the_guide_still_contains_a_countable_roster() -> None:
    """Anti-vacuous: the check below is only meaningful if something matches.

    A reformat that stops the pattern matching would turn this whole file into a
    guard that passes because it looked at nothing -- the exact shape of the three
    pins BE-9563 found freezing false statements.
    """
    claims = _roster_claims(_GUIDE.read_text(encoding="utf-8"))
    assert claims, (
        f"No roster count claim found in {_GUIDE.name}. Either the guide was reformatted "
        "out of the 'Eleven tools:' shape this guard matches -- in which case widen the "
        "pattern rather than deleting the test -- or the roster is gone entirely."
    )


def test_every_roster_count_matches_the_tools_it_lists() -> None:
    """The claim and the list must agree, and both must agree with the registry."""
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
    """Checker-must-fire, including the two true phrases that must NOT match.

    Both are real lines from the guide. A guard that flags them is a guard the next
    lane deletes.
    """
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
