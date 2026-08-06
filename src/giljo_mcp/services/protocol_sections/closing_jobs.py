# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""CH5 final-acceptance prose: closing a job, and accepting a stalled agent.

BE-9292b: extracted VERBATIM from ``chapters_reference._build_ch5_reference`` for
the 800-line file-size guardrail and that builder's shrink-only length budget --
the same seam BE-9013 / BE-9035a used to move CH3 prose into ``orchestrator_body``.
The render is byte-identical; only the location changed.

This is a plain module-level string, NOT an f-string: it is interpolated once into
CH5's f-string, so braces here are literal and must NOT be doubled. Its composition
into CH5 is pinned by identity in
``tests/services/test_protocol_sections_closing_jobs_be9292b.py`` -- without that,
editing this file could silently render nothing while still looking authoritative.
"""

from __future__ import annotations


_CLOSING_JOBS_REFERENCE = """CLOSING JOBS (FINAL ACCEPTANCE):

After verifying all deliverables from a completed agent:
- Call close_job(job_id=...) for each agent whose work is accepted
- Agents marked 'closed' will not be auto-reactivated on new messages
- Use 'decommissioned' only for failed/replaced/abandoned agents
- Lifecycle: working → complete (agent self-reports) → closed (orchestrator accepts)

ACCEPTING A STALLED AGENT (it never called complete_job):

An agent can stall mid-run and go 'silent' (the health monitor's inactivity
timeout) with its work already DONE — committed, verified, even audited. You
must not label that agent 'decommissioned'; it did not fail.

close_job refuses a 'silent' job, because 'closed' is only reachable from
'complete'. Complete it YOURSELF — complete_job accepts any non-terminal
execution, and 'silent' is not terminal:

1. Verify the deliverable independently (commits, artifacts, tests). You are
   vouching for work you did not watch happen — this step is the whole basis
   for accepting it.
2. If the agent left TODOs mid-flight, settle its ledger honestly:
   report_progress(job_id=<stalled job>, todo_items=[...], replace=true).
   Skipping this returns COMPLETION_BLOCKED naming the stranded items.
3. complete_job(job_id=<stalled job>, result={"summary": ..., "commits": [...]})
   — record what it actually delivered, not what it claimed.
4. close_job(job_id=<stalled job>) → 'closed'. Accepted, not failed.

Do NOT use write_project_closeout(force=true) to get past a stalled agent. It
does not refuse on a specialist's account — it DECOMMISSIONS it, permanently
recording accepted work under the failed/replaced/abandoned label. force is for
agents you are genuinely abandoning."""
