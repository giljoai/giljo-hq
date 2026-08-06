# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Neutrality-guard baseline — accepted offenders (BE-9257 ratchet). EMPTY.

Each entry would be (fingerprint, "file :: pattern_id :: excerpt"). The
fingerprint is sha256("file|pattern_id|normalized-line")[:12], computed by
tests/unit/test_neutrality_guard.py — content-addressed, so entries survive
line-number drift but NOT edits to the offending line. A single fingerprint
can silently cover MULTIPLE identical occurrences in the same file (no line
number is hashed) — see the guard module docstring's fingerprint-duplicate-
collapse note before assuming one entry == one offending line.

Rules of the ratchet:
- NEVER add an entry for new text you are writing — fix the text instead.
- Entries may only be added for pre-existing offenders confirmed by an audit.
- When an offender is cleaned, the stale-entry test forces removal of its
  entry here. The target state of this file is EMPTY.

**It reached EMPTY on 2026-07-27 (TSK-9314) and the target now is to keep it
that way.** An addition here is a regression, not routine maintenance.

Why it was emptied
==================
The baseline was a written record of our own file paths plus excerpts of our
own known-bad copy, and it ships to public CE (the export gate correctly does
not block it — it is neither a secret nor a credential, it is a posture
problem: a candid internal cleanup backlog handed to a customer alongside the
product). The task offered three ways out — keep it public, make the baseline
private, or clean the backlog. Cleaning it was chosen: it is the only one that
improves the product instead of hiding the evidence.

What actually happened to the 11 entries
========================================
TEN were fixed at the source — the internal citation was deleted from the
customer-rendered string, which is exactly what the guard's own hint
prescribes ("Customers cannot dereference these — delete the citation"):

- chapters_reference.py — "AGENT REACTIVATION PROTOCOL (Handover 0435c):" and
  "(server-side, Handover 0827b)" lost their handover numbers.
- giljo_guide.py — the Serials bullet lost "(IMP-6262)".
- vision_analysis.py — the legacy-field ValidationError lost "in BE-5117b".
- _job_tools.py x3 — the two "RETIRED (BE-9012b)" parameter descriptions and
  "Optional truncation recovery (BE-9083d)" lost their ticket refs.
- _tasks_prototype.py x2 — the agent-facing ``spec_note`` and the log-only
  fallback warning lost their "BE-6039" prefixes.
- _task_tools.py — NOT a leak but a Role-1 false positive: create_task's
  description was explaining the PRODUCT'S OWN serial format, and the guard
  cannot tell that shape from an internal ticket ref. Fixed by adopting the
  placeholder idiom giljo_guide.py already uses — "the serial auto-assigns in
  the TSK-nnnn form" instead of the literal "TSK-0001". That is also more
  accurate copy: TSK-0001 is only ever the FIRST task's serial. No keep-regex
  was widened, so no real ticket ref lost coverage to this fix.

The ELEVENTH could not be fixed as prose and is now a file exclusion:
_canonical_tool_list.py's ``ToolSearch(query="...")`` call template. The
literal cannot carry a "Claude Code" label without ceasing to be a pasteable
call, so it could only ever be baselined or excluded. All six of its render
sites gate the output on the harness (the prior note here claimed one caller —
that was wrong; the conclusion survives because every one of the six gates).
Reasoning recorded at ``SCAN_EXCLUDE_NAMES`` in the guard module.

The trap this file used to cover — read before re-emptying anything
==================================================================
A non-empty baseline was an ACCIDENTAL liveness canary. If the scanner ever
went blind (a directory rename making a SCAN_GLOB match nothing, an exclusion
growing too far), ``test_baseline_has_no_stale_entries`` went RED because the
baselined fingerprints stopped being observed. Emptying the baseline removes
that canary: with nothing baselined and nothing scanned, BOTH guard tests pass
vacuously and the guard is a silent no-op. Measured on 2026-07-27 before the
shrink — with the scanner stubbed to see nothing, the 11-entry baseline still
failed the stale-entry test, and an emptied one passed both.

``test_scan_surface_is_alive`` in the guard module is the DELIBERATE
replacement for that accidental canary. Do not delete it while this file is
empty — it is the only thing left that notices a scanner that has stopped
looking.
"""

# Intentionally empty — see the module docstring. An entry added here is a
# regression to explain, not a routine baseline update.
BASELINE: tuple[tuple[str, str], ...] = ()
