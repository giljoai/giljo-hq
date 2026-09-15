# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_chain_drive,
    _build_ch_sub_orchestrator,
)


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




def test_conductor_body_excises_solo_phase3_finale() -> None:
    conductor = _proto(is_chain_conductor=True)
    assert _PHASE3_FINALE not in conductor, "conductor must NOT carry the solo PHASE-3 CLOSEOUT finale"
    assert _CHAIN_FINALE in conductor, "conductor must carry the chain-finale replacement note"
    assert _ORCHESTRATOR_CONSTRAINTS in conductor, "the ORCHESTRATOR CONSTRAINTS tail must survive the finale slice"


def test_non_conductor_body_keeps_solo_phase3_finale() -> None:
    non_conductor = _proto(is_chain_conductor=False)
    assert _PHASE3_FINALE in non_conductor, "non-conductor MUST keep the solo PHASE-3 CLOSEOUT finale"
    assert _ORCHESTRATOR_CONSTRAINTS in non_conductor
    assert "### CHAIN FINALE" not in non_conductor, "the conductor chain-finale note must never leak to non-conductor"




def test_conductor_seams_live_in_ch_chain_drive() -> None:
    chapter = _build_ch_chain_drive(
        run_id="run-xyz",
        resolved_order=["p1", "p2", "p3"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id="cond-1",
        job_id="job-xyz",
    )

    assert "SCOPE IS HANDED" in chapter
    assert "scan for a project to continue" in chapter
    assert "hub_thread_id" in chapter, "the escalation sink must name the FK discovery path"
    assert 'get_context(categories=["chain"])' in chapter, "the discovery CALL must be named, not just its result"
    assert "ESCALATION" in chapter
    assert "list_threads(query=" not in chapter, "the retired substring-discovery path must not be re-introduced"
    assert "CONDUCTOR_CHAIN_INCOMPLETE" in chapter
    assert "ADVANCE" in chapter


def test_suborch_seams_live_in_ch_sub_orchestrator() -> None:
    chapter = _build_ch_sub_orchestrator(
        run_id="run-xyz",
        position=2,
        n_projects=3,
        execution_mode="multi_terminal",
    )

    assert "SCOPE IS HANDED" in chapter
    assert "scan for a project to continue" in chapter
    assert "hub_thread_id" in chapter, "the sub-orch must be told how to RESOLVE the Hub, not merely to load a tool"
    assert "list_threads(query=" not in chapter, "the retired substring-discovery path must not be re-introduced"
    low = chapter.lower()
    assert "escalat" in low, "sub-orch must carry the blocker-escalation seam (route to conductor)"
    assert "not the user" in low, "escalation must redirect AWAY from the user to the conductor"
    assert "write_project_closeout" in chapter
