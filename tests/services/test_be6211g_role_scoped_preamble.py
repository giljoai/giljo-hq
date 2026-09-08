# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6211g move (b) + BE-6214 seam relocation — role-scoped conductor/sub-orch stream.

Move (b) — root-fix the finale: the project-less chain conductor's protocol BODY
excises the solo PHASE-3 CLOSEOUT finale (its only finale is CH_CHAIN_DRIVE's
series-summary). Solo / sub-orch / worker keep the finale byte-identical. These tests
are unchanged.

BE-6214 — the override-first preamble builders (CH_CONDUCTOR_PREAMBLE /
CH_SUBORCH_PREAMBLE) are DELETED; their three seams (handed scope /
escalate-to-conductor-via-Hub / advance-not-complete_job) now live inside the chain
chapters themselves (CH_CHAIN_DRIVE / CH_SUB_ORCHESTRATOR). The former preamble-content
tests are rewritten to assert that seam relocation.

All tests are PURE (sync builders, no DB). Edition Scope: CE.
"""

from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_chain_drive,
    _build_ch_sub_orchestrator,
)


# The solo PHASE-3 finale heading (em-dash U+2014) and the kept tail anchor.
_PHASE3_FINALE = "### PHASE 3 — CLOSEOUT"
_CHAIN_FINALE = "### CHAIN FINALE (chain conductor"
_ORCHESTRATOR_CONSTRAINTS = "## ORCHESTRATOR CONSTRAINTS"


def _proto(*, is_chain_conductor: bool) -> str:
    return _generate_orchestrator_protocol(
        job_id="job-6211g",
        tenant_key="tk_6211g",
        executor_id="exec-6211g",
        execution_mode="multi_terminal",
        tool="multi_terminal",
        is_chain_conductor=is_chain_conductor,
    )


# ---------------------------------------------------------------------------
# Move (b) — conductor finale excision
# ---------------------------------------------------------------------------


def test_conductor_body_excises_solo_phase3_finale() -> None:
    """is_chain_conductor=True drops the solo PHASE-3 CLOSEOUT finale and replaces
    it with the chain-finale note; the kept ORCHESTRATOR CONSTRAINTS tail remains."""
    conductor = _proto(is_chain_conductor=True)
    assert _PHASE3_FINALE not in conductor, "conductor must NOT carry the solo PHASE-3 CLOSEOUT finale"
    assert _CHAIN_FINALE in conductor, "conductor must carry the chain-finale replacement note"
    assert _ORCHESTRATOR_CONSTRAINTS in conductor, "the ORCHESTRATOR CONSTRAINTS tail must survive the finale slice"


def test_non_conductor_body_keeps_solo_phase3_finale() -> None:
    """is_chain_conductor=False (solo / sub-orch / worker) keeps the PHASE-3 finale
    byte-for-byte and never sees the conductor chain-finale note (freeze guard:
    proves the finale trim never leaks above the is_chain_conductor early return)."""
    non_conductor = _proto(is_chain_conductor=False)
    assert _PHASE3_FINALE in non_conductor, "non-conductor MUST keep the solo PHASE-3 CLOSEOUT finale"
    assert _ORCHESTRATOR_CONSTRAINTS in non_conductor
    assert "### CHAIN FINALE" not in non_conductor, "the conductor chain-finale note must never leak to non-conductor"


# ---------------------------------------------------------------------------
# BE-6214: the override-first preamble builders are DELETED. Their three seams now
# live in the chain chapters (CH_CHAIN_DRIVE / CH_SUB_ORCHESTRATOR), so the runtime
# injector no longer prepends a separate banner. These tests assert the seam
# RELOCATION; the move-(b) finale-excision tests above are unchanged.
# ---------------------------------------------------------------------------


def test_conductor_seams_live_in_ch_chain_drive() -> None:
    """The three conductor seams (handed scope / escalation sink via the Hub /
    advance-not-complete_job) are reconciled inside CH_CHAIN_DRIVE itself, replacing
    the deleted override-first preamble."""
    chapter = _build_ch_chain_drive(
        run_id="run-xyz",
        resolved_order=["p1", "p2", "p3"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id="cond-1",
        job_id="job-xyz",
    )

    # Seam 1 — handed scope (suppress the solo continuation-hunt).
    assert "SCOPE IS HANDED" in chapter
    assert "scan for a project to continue" in chapter
    # Seam 2 — escalation SINK + Hub-thread discovery.
    #
    # BE-9291 DELIBERATELY CHANGED this probe (it is why this test was red). It used to
    # assert 'list_threads(query="run-xyz"' because the Hub really WAS discovered by
    # substring-matching the run_id out of the thread's own subject. Discovery now runs on
    # the comm_threads.sequence_run_id FK, so that instruction is gone from this chapter
    # and asserting it pinned a mechanism that no longer exists.
    #
    # The INTENT is unchanged and still enforced, and now more specifically: this chapter
    # must carry the escalation sink AND name the path the conductor actually resolves its
    # Hub with.
    assert "hub_thread_id" in chapter, "the escalation sink must name the FK discovery path"
    assert 'get_context(categories=["chain"])' in chapter, "the discovery CALL must be named, not just its result"
    assert "ESCALATION" in chapter
    # NEGATIVE: the retired substring-discovery path must not be re-introduced here.
    # Asserted on the `list_threads(query=` FORM rather than the bare tool name, and that
    # is deliberate: the bare name legitimately survives in THIS render inside the sub-orch
    # SPAWN COMMAND (launch_command_synth), so `"list_threads" not in chapter` would be
    # false today and would fail for a reason that has nothing to do with discovery.
    assert "list_threads(query=" not in chapter, "the retired substring-discovery path must not be re-introduced"
    # Seam 3 — ADVANCE, not complete_job (server refuses a premature finale).
    assert "CONDUCTOR_CHAIN_INCOMPLETE" in chapter
    assert "ADVANCE" in chapter


def test_suborch_seams_live_in_ch_sub_orchestrator() -> None:
    """The three sub-orch seams (handed scope / escalate-to-conductor / closeout-is-
    handoff) are reconciled inside CH_SUB_ORCHESTRATOR itself, replacing the deleted
    override-first preamble."""
    chapter = _build_ch_sub_orchestrator(
        run_id="run-xyz",
        position=2,
        n_projects=3,
        execution_mode="multi_terminal",
    )

    # Seam 1 — handed scope.
    assert "SCOPE IS HANDED" in chapter
    assert "scan for a project to continue" in chapter
    # Seam 2 — escalate BLOCKERS/decisions to the conductor via the Hub thread, NOT the
    # user. The discovery half MUST also assert the conductor-not-user escalation redirect —
    # that is the load-bearing half of seam 2 (BE-6214 audit: the redirect was the lost seam).
    #
    # BE-9291 DELIBERATELY CHANGED the discovery probe from `list_threads` to the FK path.
    # The old assertion was already known to be weak (its own note said "list_threads alone
    # is satisfied by the staging-complete post, an unrelated use") and after BE-9291 it went
    # weaker still: the ONLY surviving `list_threads` in this chapter is the ToolSearch
    # BOOTSTRAP line, a tool-loading hint. So it passed while proving nothing about discovery.
    assert "hub_thread_id" in chapter, "the sub-orch must be told how to RESOLVE the Hub, not merely to load a tool"
    assert "list_threads(query=" not in chapter, "the retired substring-discovery path must not be re-introduced"
    low = chapter.lower()
    assert "escalat" in low, "sub-orch must carry the blocker-escalation seam (route to conductor)"
    assert "not the user" in low, "escalation must redirect AWAY from the user to the conductor"
    # Seam 3 — closeout is the handoff (the conductor's advance signal).
    assert "write_project_closeout" in chapter
