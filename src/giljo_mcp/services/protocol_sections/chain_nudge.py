# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import textwrap
from typing import NamedTuple


_NUDGE_BLOCK = """── NATIVE HARNESS NUDGE: OPTIONAL, ON TOP OF THE HUB ───────────────────────
Every member of a multi_terminal run sits in its OWN session, so a peer may also be
reachable over your harness's native session-to-session channel (Claude Code SendMessage,
Codex `codex queue`; OpenCode has none). Judge that from YOUR OWN harness -- nothing here
knows what the other sessions are running. If you have such a channel you MAY use it as a
best-effort NUDGE IN ADDITION TO the Hub, NEVER INSTEAD OF IT:
  1. POST THE SUBSTANCE TO THE HUB THREAD FIRST. Everything that matters lives there.
  2. THEN optionally nudge the peer to go read it -- a pointer, never the content.
  3. TREAT THE NUDGE AS UNACKNOWLEDGED. It is fire-and-forget (Codex offers no reply
     path), it is persisted nowhere (a send to a session that has exited is simply
     refused and nothing queues for it), and the peer's harness may not have one at all.
     Never block, wait, or advance on a nudge.
  4. RE-DISCOVER THE PEER'S ADDRESS IMMEDIATELY BEFORE EVERY SEND (ListAgents /
     `codex agents`). Never reuse a stored name: Claude Code renames live sessions
     mid-run, and a stale name fails the send outright.
The Hub thread stays the ONLY channel every participant is required to read and the ONLY
ground truth for run state. A nudge is a doorbell; the Hub is the record."""

_NUDGE_BRIEF = """NATIVE NUDGE (optional): if your harness has a native session-to-session channel you MAY
also nudge a peer to come and read the Hub -- never instead of posting there. Rules: see
NATIVE HARNESS NUDGE."""


def native_messaging_nudge(mode: str, *, brief: bool = False, indent: str = "") -> str:
    if mode != "multi_terminal":
        return ""
    body = _NUDGE_BRIEF if brief else _NUDGE_BLOCK
    return textwrap.indent(body, indent) if indent else body


class ConductorNudge(NamedTuple):

    step_a: str
    section: str
    fork_note: str
    sink_note: str


def conductor_nudge(mode: str) -> ConductorNudge:
    block = native_messaging_nudge(mode)
    if not block:
        return ConductorNudge("", "", "", "")
    fork_note = (
        " The optional nudge below is\n"
        "NOT a fork of that: it carries no reporting at all -- every report still goes to the Hub, in\n"
        "the same words, in both modes; the nudge only tells a peer to go and read it."
    )
    return ConductorNudge(
        step_a=native_messaging_nudge(mode, brief=True, indent="        "),
        section=f"\n{block}\n",
        fork_note=fork_note,
        sink_note=f"\n\n{native_messaging_nudge(mode, brief=True)}",
    )


def suborch_nudge(mode: str) -> tuple[str, str]:
    block = native_messaging_nudge(mode)
    if not block:
        return "", ""
    return f"\n{block}\n", f"\n{native_messaging_nudge(mode, brief=True, indent='   ')}"
