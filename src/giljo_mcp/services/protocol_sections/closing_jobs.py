# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations


_CLOSING_JOBS_REFERENCE = """CLOSING JOBS (FINAL ACCEPTANCE):

After verifying all deliverables from a completed agent:
- Call finalize_job(job_id=..., caller_job_id=<your own job_id>) for each agent
  whose work is accepted. Only you can: a worker is refused (ORCHESTRATOR_ONLY)
- Agents marked 'closed' will not be auto-reactivated on new messages
- Use 'decommissioned' only for failed/replaced/abandoned agents
- Lifecycle: working → complete (agent self-reports) → closed (orchestrator accepts)

ACCEPTING A STALLED AGENT (it never called complete_job):

An agent can stall mid-run and go 'silent' (the health monitor's inactivity
timeout) with its work already DONE — committed, verified, even audited. You
must not label that agent 'decommissioned'; it did not fail.

finalize_job refuses a 'silent' job, because 'closed' is only reachable from
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
4. finalize_job(job_id=<stalled job>, caller_job_id=<your own job_id>) → 'closed'.
   Accepted, not failed.

Do NOT use write_project_closeout(force=true) to get past a stalled agent. It
does not refuse on a specialist's account — it DECOMMISSIONS it, permanently
recording accepted work under the failed/replaced/abandoned label. force is for
agents you are genuinely abandoning."""
