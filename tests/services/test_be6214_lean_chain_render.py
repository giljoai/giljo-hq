# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_drive,
    _build_ch_sub_orchestrator,
)
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    _CHAIN_PROTOCOL_REGION_END,
    _CHAIN_PROTOCOL_REGION_START,
    _CONDUCTOR_EMBEDDED_NOTE,
    _SUBORCH_PHASE1_END,
    _SUBORCH_PHASE1_NOTE,
    _SUBORCH_PHASE1_START,
    _SUBORCH_PHASE3_END,
    _SUBORCH_PHASE3_NOTE,
    _SUBORCH_PHASE3_START,
    trim_embedded_protocol_for_chain,
)


_MODE = "multi_terminal"
_ORDER = ["p1", "p2", "p3"]
_CANONICAL_ADVANCE_SENTENCE = "that is the server's ONE authoritative"


def _solo_orchestrator_protocol(*, is_chain_conductor: bool) -> str:
    return _generate_orchestrator_protocol(
        job_id="job-6214",
        tenant_key="tk_6214",
        executor_id="exec-6214",
        execution_mode=_MODE,
        tool=_MODE,
        is_chain_conductor=is_chain_conductor,
    )


def _conductor_render() -> str:
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    parts = [
        _build_ch_capability(execution_mode=_MODE, can_spawn_terminals=True),
        _build_ch_chain_drive(
            run_id="run-6214",
            resolved_order=_ORDER,
            current_index=0,
            execution_mode=_MODE,
            conductor_agent_id="cond-6214",
            job_id="job-6214",
        ),
        trim_embedded_protocol_for_chain(full_protocol, "conductor"),
    ]
    return "\n\n".join(parts)


def _suborch_render() -> str:
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=False)
    parts = [
        _build_ch_sub_orchestrator(
            run_id="run-6214",
            position=2,
            n_projects=3,
            execution_mode=_MODE,
            chain_mission=None,
            phase="implementation",
        ),
        trim_embedded_protocol_for_chain(full_protocol, "sub_orchestrator", phase="implementation"),
    ]
    return "\n\n".join(parts)


def _b(text: str) -> int:
    return len(text.encode("utf-8"))




def test_conductor_render_is_lean_with_floor() -> None:
    render_bytes = _b(_conductor_render())
    assert render_bytes >= 12_000, f"conductor render fell below the irreducible floor: {render_bytes}"
    assert render_bytes <= 23_400, f"conductor render regressed above the lean ceiling: {render_bytes}"


def test_conductor_embedded_trim_removes_meaningful_span() -> None:
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    trimmed = trim_embedded_protocol_for_chain(full_protocol, "conductor")
    assert _b(full_protocol) - _b(trimmed) >= 4_000, "conductor embedded trim must remove a meaningful span"




def test_suborch_render_band() -> None:
    render_bytes = _b(_suborch_render())
    assert render_bytes >= 19_500, f"sub-orch render fell below the band: {render_bytes}"
    assert render_bytes <= 22_500, f"sub-orch render regressed above the band: {render_bytes}"




def test_conductor_advance_gate_sentence_stated_once() -> None:
    render = _conductor_render()
    assert render.count(_CANONICAL_ADVANCE_SENTENCE) == 1, (
        f"canonical advance-gate sentence must appear exactly once, got {render.count(_CANONICAL_ADVANCE_SENTENCE)}"
    )


def test_conductor_drive_todo_wording_survives() -> None:
    from giljo_mcp.domain.todo_kinds import CHAIN_DRIVE_TODO_PATTERN

    render = _conductor_render()
    assert CHAIN_DRIVE_TODO_PATTERN.search(render), "lean conductor render must retain drive-TODO keyword wording"




def test_preamble_markers_absent_from_both_renders() -> None:
    conductor = _conductor_render()
    suborch = _suborch_render()
    for marker in ("CH_CONDUCTOR_PREAMBLE", "CH_SUBORCH_PREAMBLE"):
        assert marker not in conductor, f"{marker} must be absent from the conductor render"
        assert marker not in suborch, f"{marker} must be absent from the sub-orch render"


def test_three_seams_relocated_into_conductor_chapters() -> None:
    render = _conductor_render()
    assert "SCOPE IS HANDED" in render
    assert "scan for a project to continue" in render
    assert "hub_thread_id" in render
    assert "ESCALATION" in render
    assert "CONDUCTOR_CHAIN_INCOMPLETE" in render
    assert "ADVANCE" in render


def test_three_seams_relocated_into_suborch_chapter() -> None:
    render = _suborch_render()
    assert "SCOPE IS HANDED" in render
    assert "scan for a project to continue" in render
    assert "hub_thread_id" in render
    assert "write_project_closeout" in render




def test_trim_is_graceful_on_anchor_drift_and_unknown_role() -> None:
    no_anchors = "a protocol with none of the BE-6214 trim anchors present"
    assert trim_embedded_protocol_for_chain(no_anchors, "conductor") == no_anchors
    assert trim_embedded_protocol_for_chain(no_anchors, "sub_orchestrator") == no_anchors

    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    assert trim_embedded_protocol_for_chain(full_protocol, "solo") == full_protocol
    assert trim_embedded_protocol_for_chain(full_protocol, "worker") == full_protocol
    assert trim_embedded_protocol_for_chain("", "conductor") == ""




def test_conductor_reverse_splice_lock() -> None:
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    trimmed = trim_embedded_protocol_for_chain(full_protocol, "conductor")
    start = full_protocol.find(_CHAIN_PROTOCOL_REGION_START)
    end = full_protocol.find(_CHAIN_PROTOCOL_REGION_END)
    excised = full_protocol[start:end]
    reconstructed = trimmed.replace(_CONDUCTOR_EMBEDDED_NOTE, excised, 1)
    assert reconstructed == full_protocol, "reverse-splice must reproduce the original conductor protocol exactly"


def test_suborch_reverse_splice_lock() -> None:
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=False)
    trimmed = trim_embedded_protocol_for_chain(full_protocol, "sub_orchestrator")
    p1_excised = full_protocol[full_protocol.find(_SUBORCH_PHASE1_START) : full_protocol.find(_SUBORCH_PHASE1_END)]
    p3_excised = full_protocol[full_protocol.find(_SUBORCH_PHASE3_START) : full_protocol.find(_SUBORCH_PHASE3_END)]
    reconstructed = trimmed.replace(_SUBORCH_PHASE1_NOTE, p1_excised, 1).replace(_SUBORCH_PHASE3_NOTE, p3_excised, 1)
    assert reconstructed == full_protocol, "reverse-splice must reproduce the original sub-orch protocol exactly"
