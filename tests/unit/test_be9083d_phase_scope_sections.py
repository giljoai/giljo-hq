# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_sub_orchestrator
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    _SUBORCH_PHASE1_NOTE,
    _SUBORCH_PHASE1_START,
    _SUBORCH_STAGING_IMPL_NOTE,
    _SUBORCH_STAGING_IMPL_REGION_END,
    _SUBORCH_STAGING_IMPL_REGION_START,
    trim_embedded_protocol_for_chain,
)
from giljo_mcp.services.protocol_survival import (
    PROTOCOL_END_MARKER,
    SECTION_MAX_CHARS,
    SECTION_MAX_LINES,
    build_protocol_toc,
    build_truncation_check,
    compute_next_required_actions,
    split_protocol_sections,
)


_RUN_ID = "run-9083d"
_CHAIN_MISSION = (
    "### P_1 (upstream):\nconsumes = repo baseline\nproduces = api scaffolding\nmust leave = routers registered\n\n"
    "### P_2 (this project):\n"
    + "\n".join(f"contract line {i} = deliverable detail {i}" for i in range(1, 30))
    + "\n\n"
    "### P_3 (downstream):\nconsumes = P_2 output\nproduces = e2e coverage\nmust leave = CI green"
)


def _solo_protocol(tool: str) -> str:
    return _generate_orchestrator_protocol(
        job_id="job-9083d",
        tenant_key="tk_9083d",
        executor_id="exec-9083d",
        execution_mode="multi_terminal",
        tool=tool,
        is_chain_conductor=False,
    )


def _suborch_render(*, phase: str, tool: str = "multi_terminal") -> str:
    parts = [
        _build_ch_sub_orchestrator(
            run_id=_RUN_ID,
            position=2,
            n_projects=3,
            execution_mode="multi_terminal",
            chain_mission=_CHAIN_MISSION,
            phase=phase,
        ),
        trim_embedded_protocol_for_chain(_solo_protocol(tool), "sub_orchestrator", phase=phase),
    ]
    return "\n\n".join(parts)


def _finalized(protocol: str) -> str:
    return protocol + f"\n\n{PROTOCOL_END_MARKER}"




def test_bridge_line_survives_in_staging_slice() -> None:
    staging = _suborch_render(phase="staging")
    assert "call get_job_mission ONCE" in staging
    assert "no gate" in staging
    assert "Do NOT wait for a human" in staging
    assert "5. CONTINUE TO IMPLEMENTATION (no gate, no wait)" in staging


def test_bridge_line_survives_in_staging_checklist() -> None:
    checklist = compute_next_required_actions(job_type="orchestrator", phase="staging", is_chain_member=True)
    assert checklist is not None
    joined = "\n".join(checklist)
    assert "get_job_mission ONCE" in joined
    assert "no gate" in joined


def test_staging_slice_omits_implementation_regions() -> None:
    staging = _suborch_render(phase="staging")
    assert "THE COORDINATION LOOP" not in staging
    assert "### RESTING STATES" not in staging
    assert "### PHASE 3" not in staging
    assert "Closeout steps (order matters)" not in staging
    assert _SUBORCH_STAGING_IMPL_NOTE in staging
    assert "## ORCHESTRATOR CONSTRAINTS" in staging


def test_implementation_render_keeps_the_coordination_loop() -> None:
    impl = _suborch_render(phase="implementation")
    assert "THE COORDINATION LOOP" in impl
    assert "### RESTING STATES" in impl
    assert "Closeout steps (order matters):" in impl


def test_implementation_chapter_collapses_done_staging_steps() -> None:
    impl = _suborch_render(phase="implementation")
    assert "2. READ YOUR CONTRACT" not in impl
    assert "3. STAGE" not in impl
    assert "4. END STAGING + POST" not in impl
    assert "contract line 1 = deliverable detail 1" not in impl, "the contract slice must not re-ship"
    assert "STAGING -- ALREADY COMPLETE" in impl
    assert "hub_thread_id" in impl
    assert "ESCALATION" in impl
    assert "5. CONTINUE TO IMPLEMENTATION (no gate, no wait)" in impl
    assert "7. CLOSE OUT + REPORT" in impl


def test_staging_chapter_and_default_are_byte_identical_to_full_render() -> None:
    kwargs = {
        "run_id": _RUN_ID,
        "position": 2,
        "n_projects": 3,
        "execution_mode": "multi_terminal",
        "chain_mission": _CHAIN_MISSION,
    }
    default = _build_ch_sub_orchestrator(**kwargs)
    staging = _build_ch_sub_orchestrator(**kwargs, phase="staging")
    assert staging == default
    assert "2. READ YOUR CONTRACT" in default
    assert "4. END STAGING + POST" in default


def test_trim_default_phase_matches_implementation_phase() -> None:
    solo = _solo_protocol("multi_terminal")
    assert trim_embedded_protocol_for_chain(solo, "sub_orchestrator") == trim_embedded_protocol_for_chain(
        solo, "sub_orchestrator", phase="implementation"
    )


def test_staging_trim_reverse_splice_lock() -> None:
    solo = _solo_protocol("multi_terminal")
    trimmed = trim_embedded_protocol_for_chain(solo, "sub_orchestrator", phase="staging")
    p1_excised = solo[solo.find(_SUBORCH_PHASE1_START) : solo.find(_SUBORCH_STAGING_IMPL_REGION_START)]
    impl_excised = solo[solo.find(_SUBORCH_STAGING_IMPL_REGION_START) : solo.find(_SUBORCH_STAGING_IMPL_REGION_END)]
    reconstructed = trimmed.replace(_SUBORCH_PHASE1_NOTE, p1_excised, 1).replace(
        _SUBORCH_STAGING_IMPL_NOTE, impl_excised, 1
    )
    assert reconstructed == solo


def test_staging_trim_is_graceful_on_anchor_drift() -> None:
    no_anchors = "a protocol with none of the trim anchors present"
    assert trim_embedded_protocol_for_chain(no_anchors, "sub_orchestrator", phase="staging") == no_anchors




def _all_renders() -> dict[str, str]:
    return {
        "suborch_staging_mt": _finalized(_suborch_render(phase="staging", tool="multi_terminal")),
        "suborch_impl_mt": _finalized(_suborch_render(phase="implementation", tool="multi_terminal")),
        "suborch_staging_cc": _finalized(_suborch_render(phase="staging", tool="claude-code")),
        "suborch_impl_cc": _finalized(_suborch_render(phase="implementation", tool="claude-code")),
        "solo_orchestrator": _finalized(_solo_protocol("multi_terminal")),
    }


def test_sections_join_back_to_the_exact_full_protocol() -> None:
    for name, protocol in _all_renders().items():
        sections = split_protocol_sections(protocol)
        assert sections, f"{name}: splitter returned no sections"
        assert "".join(content for _, content in sections) == protocol, f"{name}: sections do not rejoin"


def test_section_names_are_unique_and_toc_is_accurate() -> None:
    for name, protocol in _all_renders().items():
        sections = split_protocol_sections(protocol)
        names = [n for n, _ in sections]
        assert len(set(names)) == len(names), f"{name}: duplicate section names {names}"
        toc = build_protocol_toc(sections)
        assert [e["section"] for e in toc] == names
        for entry, (_, content) in zip(toc, sections, strict=True):
            assert entry["chars"] == len(content)
            assert entry["lines"] == len(content.splitlines())


def test_every_section_fits_the_harness_floor_budget() -> None:
    assert SECTION_MAX_CHARS <= 8_192
    assert SECTION_MAX_LINES <= 200
    for name, protocol in _all_renders().items():
        for section_name, content in split_protocol_sections(protocol):
            assert len(content) <= SECTION_MAX_CHARS, f"{name}/{section_name}: {len(content)} chars"
            assert len(content.splitlines()) <= SECTION_MAX_LINES, (
                f"{name}/{section_name}: {len(content.splitlines())} lines"
            )


def test_last_section_carries_the_end_marker() -> None:
    for protocol in _all_renders().values():
        sections = split_protocol_sections(protocol)
        assert sections[-1][1].endswith(PROTOCOL_END_MARKER)


def test_splitter_hard_splits_a_pathological_oversized_section() -> None:
    monster = "## MONSTER SECTION\n" + ("x" * 120 + "\n") * 400
    sections = split_protocol_sections(monster)
    assert len(sections) > 1
    assert "".join(c for _, c in sections) == monster
    for section_name, content in sections:
        assert len(content) <= SECTION_MAX_CHARS, section_name
        assert len(content.splitlines()) <= SECTION_MAX_LINES, section_name




def test_truncation_check_names_section_fetch_recovery() -> None:
    text = build_truncation_check(41_234)
    assert "~41234 chars" in text
    assert PROTOCOL_END_MARKER in text
    assert "protocol_etag" in text
    assert "section=" in text
    assert "protocol_toc" in text
    assert "ships later" not in text
