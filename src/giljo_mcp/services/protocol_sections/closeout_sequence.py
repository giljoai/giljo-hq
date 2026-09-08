# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9543: single source of truth for the orchestrator closeout call sequence.

Three surfaces used to each carry their own copy of "what to call, in what order, to
close a project" -- ``worker_body.py``'s (wrong) Phase 4 addendum, this file's own
``required_sequence`` rejection payload, and ``giljo_guide.py``'s prose -- and they
disagreed: the first two told the agent to call ``write_memory_entry`` between
``complete_job`` and ``write_project_closeout``; the guide correctly said that call is
redundant. Verified by call path: ``write_project_closeout`` (``close_project_and_update_
memory`` -> ``_build_and_persist_memory_entry`` in ``tools/project_closeout.py``) already
persists its own ``project_closeout`` 360 entry. A ``write_memory_entry`` call in between
does not fail -- it just writes a SECOND, redundant 360 entry for the same project.

``CANONICAL_CLOSEOUT_STEPS`` is the one list every rejection payload / prose surface
should build its numbered steps from, so a future edit to the sequence has one place to
change. ``tests/unit/test_be9543_closeout_sequence_consistency.py`` pins that no
agent-facing text re-introduces ``write_memory_entry`` as a required closeout step.
"""

from __future__ import annotations


# Bare tool-call templates, in required order. ``{job_id}`` is the only substitution
# point any caller needs -- everything else is a literal, reusable across every render
# site (the rejection payload here, and any future prose surface).
CANONICAL_CLOSEOUT_STEPS: tuple[str, ...] = (
    "complete_job(job_id='{job_id}') -- complete yourself first",
    "write_project_closeout(force=false) -- writes the 360 closeout entry and finalizes "
    "the project (should now pass since all agents are complete)",
)


def build_required_sequence(job_id: str) -> list[str]:
    """Render ``CANONICAL_CLOSEOUT_STEPS`` as a numbered list for a rejection payload."""
    return [f"{i}. {step.format(job_id=job_id)}" for i, step in enumerate(CANONICAL_CLOSEOUT_STEPS, start=1)]
