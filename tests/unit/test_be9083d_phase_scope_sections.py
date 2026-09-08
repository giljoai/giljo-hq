# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9083d — phase-scoped chain protocol + section-fetch recovery (unit layer).

Written FAIL-FIRST (the bridge test is the non-negotiable regression guard for the
BE-6206 stall-after-staging class): a staging-phase chain sub-orchestrator fetch must
STILL carry the bridge instruction ("after complete_job, call get_job_mission ONCE,
no gate, do NOT wait") in BOTH the next_required_actions checklist and the staging
protocol slice, even after phase-scoping removes the implementation-only regions.

Also pinned here:
  * single-render-then-slice: ``split_protocol_sections`` returns contiguous slices
    whose concatenation reproduces the FINAL full_protocol byte-for-byte (never a
    re-render — drift risk).
  * per-section budget: every section of the worst-case render (chain sub-orch,
    multi_terminal AND claude-code, staging AND implementation) fits the ~8KB /
    200-line cross-harness floor (Codex CLI ~10KiB/256-line silent cut).
  * phase-scoping shape: the staging slice drops PHASE 2 / RESTING / PHASE 3; the
    implementation chapter collapses the already-done staging steps 2-4; reverse-
    splice locks prove each cut removes EXACTLY its anchored span.
  * the BE-9083a head sentinel now names the REAL recovery: section=<name> refetch
    (closing the dangling reference 9083a deliberately left).

Pure functions — no DB, no module-level mutable state → parallel-safe under
pytest-xdist. Edition Scope: Both.
"""

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
# A realistic conductor-authored chain mission: this sub-orch's own block plus two
# sibling blocks (the 9083c slicer keeps only P_2's).
_CHAIN_MISSION = (
    "### P_1 (upstream):\nconsumes = repo baseline\nproduces = api scaffolding\nmust leave = routers registered\n\n"
    "### P_2 (this project):\n"
    + "\n".join(f"contract line {i} = deliverable detail {i}" for i in range(1, 30))
    + "\n\n"
    "### P_3 (downstream):\nconsumes = P_2 output\nproduces = e2e coverage\nmust leave = CI green"
)


def _solo_protocol(tool: str) -> str:
    """The embedded solo full_protocol the injector receives for a sub-orch."""
    return _generate_orchestrator_protocol(
        job_id="job-9083d",
        tenant_key="tk_9083d",
        executor_id="exec-9083d",
        execution_mode="multi_terminal",
        tool=tool,
        is_chain_conductor=False,
    )


def _suborch_render(*, phase: str, tool: str = "multi_terminal") -> str:
    """Reconstruct the sub-orch render EXACTLY as inject_conductor_chain_drive does."""
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
    """Mirror finalize_mission_wire_fields' tail-marker append (the FINAL wire bytes)."""
    return protocol + f"\n\n{PROTOCOL_END_MARKER}"


# ---------------------------------------------------------------------------
# 1. THE BRIDGE (non-negotiable — the BE-6206 stall-after-staging guard)
# ---------------------------------------------------------------------------


def test_bridge_line_survives_in_staging_slice() -> None:
    """The staging-phase sub-orch protocol slice must still instruct: after
    complete_job (staging-end), call get_job_mission ONCE — no gate, do NOT wait.
    Phase-scoping may remove implementation-only regions but NEVER the bridge."""
    staging = _suborch_render(phase="staging")
    assert "call get_job_mission ONCE" in staging
    assert "no gate" in staging
    assert "Do NOT wait for a human" in staging
    # CH_SUB_ORCHESTRATOR step 5 (the combined-flow bridge step) is intact.
    assert "5. CONTINUE TO IMPLEMENTATION (no gate, no wait)" in staging


def test_bridge_line_survives_in_staging_checklist() -> None:
    """The post-9083a equivalent of the bridge rides in next_required_actions for the
    chain sub-orch staging cell (the authoritative early-wire checklist)."""
    checklist = compute_next_required_actions(job_type="orchestrator", phase="staging", is_chain_member=True)
    assert checklist is not None
    joined = "\n".join(checklist)
    assert "get_job_mission ONCE" in joined
    assert "no gate" in joined


def test_staging_slice_omits_implementation_regions() -> None:
    """Phase-scoping actually fires: the staging fetch drops the implementation
    coordination loop, resting states, and closeout procedure (they arrive with the
    post-staging-end get_job_mission)."""
    staging = _suborch_render(phase="staging")
    assert "THE COORDINATION LOOP" not in staging
    assert "### RESTING STATES" not in staging
    assert "### PHASE 3" not in staging
    assert "Closeout steps (order matters)" not in staging
    # The deferral note itself restates the bridge, and the constraints tail is kept.
    assert _SUBORCH_STAGING_IMPL_NOTE in staging
    assert "## ORCHESTRATOR CONSTRAINTS" in staging


def test_implementation_render_keeps_the_coordination_loop() -> None:
    """The post-staging-end fetch serves the implementation regions in full."""
    impl = _suborch_render(phase="implementation")
    assert "THE COORDINATION LOOP" in impl
    assert "### RESTING STATES" in impl
    assert "Closeout steps (order matters):" in impl


def test_implementation_chapter_collapses_done_staging_steps() -> None:
    """The implementation-phase CH_SUB_ORCHESTRATOR collapses the already-done staging
    steps 2-4 (and their inlined contract slice) to a compact marker, KEEPING the step
    numbering that the PHASE-1/PHASE-3 notes cross-reference (step 5 / step 7)."""
    impl = _suborch_render(phase="implementation")
    assert "2. READ YOUR CONTRACT" not in impl
    assert "3. STAGE" not in impl
    assert "4. END STAGING + POST" not in impl
    assert "contract line 1 = deliverable detail 1" not in impl, "the contract slice must not re-ship"
    assert "STAGING -- ALREADY COMPLETE" in impl
    # The Hub-thread discovery + escalation seams survive the collapse (load-bearing).
    # BE-9291 DELIBERATELY CHANGED the discovery probe from `list_threads` to the FK path.
    # The collapsed implementation chapter still names the ToolSearch bootstrap, so the old
    # assertion survived the collapse whether or not the discovery seam did — it could not
    # have caught the very regression this test exists to catch.
    assert "hub_thread_id" in impl
    assert "ESCALATION" in impl
    # Numbered cross-reference targets stay intact.
    assert "5. CONTINUE TO IMPLEMENTATION (no gate, no wait)" in impl
    assert "7. CLOSE OUT + REPORT" in impl


def test_staging_chapter_and_default_are_byte_identical_to_full_render() -> None:
    """phase='staging' and phase=None (every pre-9083d caller) render the FULL chapter
    byte-identically — the combined staging+implementation script is the sub-orch's
    contract during staging, and default callers keep today's exact bytes."""
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
    """trim(..., phase=None) == trim(..., phase='implementation'): the pre-9083d cuts
    are the implementation cuts, so existing callers/tests keep today's bytes."""
    solo = _solo_protocol("multi_terminal")
    assert trim_embedded_protocol_for_chain(solo, "sub_orchestrator") == trim_embedded_protocol_for_chain(
        solo, "sub_orchestrator", phase="implementation"
    )


def test_staging_trim_reverse_splice_lock() -> None:
    """Splicing the excised spans back into the staging-trimmed protocol reproduces the
    original solo protocol byte-for-byte — each staging cut removes EXACTLY its
    anchored span and every kept region is byte-identical."""
    solo = _solo_protocol("multi_terminal")
    trimmed = trim_embedded_protocol_for_chain(solo, "sub_orchestrator", phase="staging")
    p1_excised = solo[solo.find(_SUBORCH_PHASE1_START) : solo.find(_SUBORCH_STAGING_IMPL_REGION_START)]
    impl_excised = solo[solo.find(_SUBORCH_STAGING_IMPL_REGION_START) : solo.find(_SUBORCH_STAGING_IMPL_REGION_END)]
    reconstructed = trimmed.replace(_SUBORCH_PHASE1_NOTE, p1_excised, 1).replace(
        _SUBORCH_STAGING_IMPL_NOTE, impl_excised, 1
    )
    assert reconstructed == solo


def test_staging_trim_is_graceful_on_anchor_drift() -> None:
    """A protocol missing the staging anchors is returned unchanged (no raise, no
    corruption) — same degradation contract as every other anchor-slice cut."""
    no_anchors = "a protocol with none of the trim anchors present"
    assert trim_embedded_protocol_for_chain(no_anchors, "sub_orchestrator", phase="staging") == no_anchors


# ---------------------------------------------------------------------------
# 2. Single-render-then-slice: sections are byte-identical contiguous slices
# ---------------------------------------------------------------------------


def _all_renders() -> dict[str, str]:
    return {
        "suborch_staging_mt": _finalized(_suborch_render(phase="staging", tool="multi_terminal")),
        "suborch_impl_mt": _finalized(_suborch_render(phase="implementation", tool="multi_terminal")),
        "suborch_staging_cc": _finalized(_suborch_render(phase="staging", tool="claude-code")),
        "suborch_impl_cc": _finalized(_suborch_render(phase="implementation", tool="claude-code")),
        "solo_orchestrator": _finalized(_solo_protocol("multi_terminal")),
    }


def test_sections_join_back_to_the_exact_full_protocol() -> None:
    """join(sections) == full_protocol, byte-for-byte, zero separator residue — the
    sections are SLICES of the one final render, never a re-render."""
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
    """Worst-case render (chain sub-orch, both modes, both phases): every section must
    individually fit the ~8KB / 200-line cross-harness floor, so a per-section refetch
    can never itself be truncated."""
    assert SECTION_MAX_CHARS <= 8_192
    assert SECTION_MAX_LINES <= 200
    for name, protocol in _all_renders().items():
        for section_name, content in split_protocol_sections(protocol):
            assert len(content) <= SECTION_MAX_CHARS, f"{name}/{section_name}: {len(content)} chars"
            assert len(content.splitlines()) <= SECTION_MAX_LINES, (
                f"{name}/{section_name}: {len(content.splitlines())} lines"
            )


def test_last_section_carries_the_end_marker() -> None:
    """The tail sentinel is part of the final slice, so a per-section refetch can verify
    it received the protocol tail."""
    for protocol in _all_renders().values():
        sections = split_protocol_sections(protocol)
        assert sections[-1][1].endswith(PROTOCOL_END_MARKER)


def test_splitter_hard_splits_a_pathological_oversized_section() -> None:
    """A section that exceeds the budget (here: one giant header-less block) is split
    into budget-fitting parts that still rejoin byte-identically."""
    monster = "## MONSTER SECTION\n" + ("x" * 120 + "\n") * 400
    sections = split_protocol_sections(monster)
    assert len(sections) > 1
    assert "".join(c for _, c in sections) == monster
    for section_name, content in sections:
        assert len(content) <= SECTION_MAX_CHARS, section_name
        assert len(content.splitlines()) <= SECTION_MAX_LINES, section_name


# ---------------------------------------------------------------------------
# 3. The 9083a head sentinel now names the REAL recovery (section=<name>)
# ---------------------------------------------------------------------------


def test_truncation_check_names_section_fetch_recovery() -> None:
    """BE-9083d closes the dangling reference 9083a deliberately left: the head
    sentinel names the section=<name> refetch (with protocol_toc as the name source)
    alongside the protocol_etag refetch, and no longer defers to a future ship."""
    text = build_truncation_check(41_234)
    assert "~41234 chars" in text
    assert PROTOCOL_END_MARKER in text
    assert "protocol_etag" in text
    assert "section=" in text
    assert "protocol_toc" in text
    assert "ships later" not in text
