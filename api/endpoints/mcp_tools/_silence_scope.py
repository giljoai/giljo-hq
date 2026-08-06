# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9303 — which MCP tools may clear an agent's ``'silent'`` status.

``_base._call_tool``'s ``auto_clear_silent`` post-hook used to fire on ANY
successful call carrying a ``job_id``. That is the defect: the hook has no caller
identity, so ``get_context(categories=['todos'], job_id=...)`` — the read
documented FOR force-recovery, and therefore the likeliest call from an
orchestrator looking at a stranded job — cleared the very ``'silent'`` flag that
``close_job``'s recovery hint keys on. **The orchestrator's own diagnostic read
disarmed the hint before it could fire.**

BE-9292b proved this cannot be fixed at the hint layer:
``clear_silent_to_working`` also stamps ``last_progress_at = now()``, so a
staleness gate is defeated by the same mutation, and a bystander read leaves a row
byte-identical to a genuine revival. See
``tests/services/test_be9292b_silence_clear_disarms_hint.py``.

THE CRITERION — whose job is the ``job_id``?

The hook exists to notice that *an agent is alive*. A call is evidence of that
only when the ``job_id`` it carries is **the caller's own job**. Where the tool's
whole purpose is to act on **someone else's** job, the call says nothing about
whether that job's agent is alive, and must not speak for it.

This is deliberately NOT a plain "writes clear, reads do not" split. ``get_job_mission``
is a read and belongs on the clearing side (it is the agent's own boot/refresh call —
``mission_service`` already stamps ``last_progress_at`` on it); an agent whose only
job-carrying calls were mission refreshes would otherwise be marked silent and STAY
silent, becoming a target for a hint meant for unattended agents.

MUSEUM RULE. ``auto_clear_silent`` is load-bearing and has already been lost once:
``dd306cb36`` re-wired it after the 0846 SDK migration dropped it, leaving
live-but-slow agents reading ``'silent'`` forever. That incident is reproduced and
watched red in
``tests/integration/test_be9303_auto_clear_silent_caller_scope_mcp_boundary.py``
before this scope was introduced. This narrows the hook; it never removes it.

Every MCP tool accepting ``job_id`` must appear in exactly one set below — the
test above fails on any unclassified tool, so a new one cannot inherit
silence-clearing by accident, which is how the defect arose.

THE LIMIT OF THE CRITERION (TSK-9318, measured). "Whose job" is a property of the
CALLER, and this boundary carries no caller job identity — only ``tenant_key`` and
``user_id``. The hook therefore clears whatever ``job_id`` it is handed, and an
orchestrator calling a clearing tool on a WORKER's job_id would clear that worker's
flag exactly as the worker's own call would. Observation says this does not happen
in practice, but that is a usage convention these names satisfy, not an invariant
the code enforces. Closing it would need a caller-identity signal that does not
exist at this layer. The residual is characterized at
``tests/integration/test_tsk9318_silence_clearing_classification_proof_mcp_boundary.py``
so it stays measured rather than assumed; that file also pins every name here, so a
classification can no longer rest on a comment alone.
"""

from __future__ import annotations


# The caller is acting on ITS OWN job — the call is proof that agent is alive.
SILENCE_CLEARING_TOOLS: frozenset[str] = frozenset(
    {
        # The agent's progress heartbeat; stamps last_progress_at itself.
        "report_progress",
        # The agent's own mission fetch/refresh — its boot call.
        "get_job_mission",
        # The agent fetching its own staging instructions. TSK-9318 measured this
        # rather than reading it: 20 observed calls — 12 on the caller's own job, 7
        # on jobs never heartbeat anywhere, 1 unresolved (a second session first
        # heartbeat that job ten hours later, which reads equally well as a staging
        # orchestrator or as one agent carrying a second job; the transcripts cannot
        # separate them, so it is recorded, not counted as a counter-example).
        "get_staging_instructions",
        # The agent declaring its own state (idle/sleeping/blocked/...). TSK-9318:
        # 47 observed calls, 47 on the caller's own job, zero cross-agent uses.
        "set_agent_status",
        # Orchestrator-only (BE-9054 rejects workers), and its wrapper forwards
        # job_id into _call_tool, so the hook is genuinely live for it. TSK-9318
        # found ZERO calls in 530 sessions, so — unlike its two neighbours — this
        # entry rests on the parameter's own contract, not on observation. Pinned
        # only as far as it can be: that it reaches the hook at all.
        "request_approval",
    }
)

# The tool's purpose is to inspect, drive or accept SOMEONE ELSE'S job. A call
# here proves the caller is alive, never the job's agent.
NON_SILENCE_CLEARING_TOOLS: frozenset[str] = frozenset(
    {
        # THE DOCUMENTED DISARM. job_id is accepted only for the 'todos'
        # force-recovery category, so excluding it costs an agent's ordinary
        # get_context calls nothing — those carry no job_id and never reached
        # this hook at all.
        "get_context",
        # An orchestrator reading a worker's recorded result.
        "get_agent_result",
        # Final acceptance by the orchestrator — and the call that RAISES the
        # recovery hint. Had it cleared silence first, the hint could never fire
        # on a retry.
        "close_job",
        # Orchestrator-driven reactivation decision about another agent's job.
        # NOTE the names: the ``resolve_reactivation`` TOOL never reaches
        # ``_call_tool`` under its own name — it branches on ``action`` and
        # dispatches to one of these two internal targets, which are the values
        # ``method_name`` actually takes. Classifying "resolve_reactivation" here
        # would be decoration that never matches anything.
        "reactivate_job",
        "dismiss_reactivation",
        # An orchestrator rewriting a worker's mission.
        "update_job_mission",
        # Ambiguous by design: the agent completes its own job, but BE-9292b
        # documents the ORCHESTRATOR calling it to accept a stalled agent's
        # verified deliverable. Excluded on the conservative side — and moot,
        # since a successful complete_job moves the execution to 'complete'
        # regardless of the silent flag.
        "complete_job",
    }
)
