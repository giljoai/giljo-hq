# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Name the orchestrator's coordination thread in its rendered protocol (TSK-9459).

Every ``get_thread_history`` / ``post_to_thread`` call in the orchestrator body
renders the literal ``<your coordination thread>``. The orchestrator was never
given that id — ``get_agent_mission`` resolved the project's bound Hub thread for
every job type EXCEPT ``orchestrator`` — so the placeholder was unresolvable and
the orchestrator stayed off the thread its own workers joined.

The server now also enrols the orchestrator structurally (see
``services/comm_thread_enrolment``). Being ON the thread and being able to NAME it
are different things and both are needed: a participant that cannot name its
thread still cannot post to it.

This is a post-render substitution on verbatim anchors rather than an f-string
parameter, matching ``orchestrator_body``'s own established
``_apply_anchor_slice`` idiom — and for the same reason that module uses it: that
file sits on the 800-line cap. Like those slices, a missing anchor is a graceful
no-op: the body renders exactly as before rather than raising or corrupting.
"""

from __future__ import annotations

import logging


logger = logging.getLogger(__name__)

# The placeholder as orchestrator_body renders it, and the Phase-1 line the
# enrolment note is inserted ABOVE. Both verbatim, both drift-tolerant.
_PLACEHOLDER_CALL = "thread_id=<your coordination thread>"
_PHASE1_ANCHOR = '   - "I will actively coordinate. Wake me when agents need attention or on status changes."'


def apply_thread_reference(protocol: str, comm_thread_id: str | None) -> str:
    """Replace the coordination-thread placeholder with the resolved thread id.

    Also inserts one Phase-1 line naming the thread. That line is a statement of
    FACT about what the server already did, deliberately NOT an instruction to
    join: enrolment is the mechanism's job, and prose must never be used to
    enforce what the tool guarantees.

    ``comm_thread_id`` of None (a project-less conductor, or a thread that could
    not be resolved) returns ``protocol`` untouched — byte-identical to the
    pre-TSK-9459 render, so nothing is claimed that is not true.
    """
    if not protocol or not comm_thread_id:
        return protocol
    if _PLACEHOLDER_CALL not in protocol:
        logger.warning(
            "coordination-thread placeholder not found in the orchestrator protocol; "
            "the render drifted. Leaving it unchanged."
        )
        return protocol
    protocol = protocol.replace(_PLACEHOLDER_CALL, f'thread_id="{comm_thread_id}"')
    note = (
        f"   - Your coordination thread is `{comm_thread_id}` — the server enrolled you on "
        "it while serving this mission, so a post directed at you reaches you. Use that id "
        "for every `get_thread_history` / `post_to_thread` call below.\n"
    )
    return protocol.replace(_PHASE1_ANCHOR, note + _PHASE1_ANCHOR, 1)
