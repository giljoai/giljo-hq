# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6214 — lean role-scoped CHAIN protocol render.

The runtime conductor_chain_injector no longer prepends an override-first preamble
and no longer re-ships the embedded SOLO protocol verbatim. Instead it lean-trims the
embedded ``full_protocol`` via ``trim_embedded_protocol_for_chain`` (the existing
anchor-slice idiom) before appending the chain chapters, and the three role seams
(handed scope / escalate-to-conductor-via-Hub / advance-not-complete_job) live in
CH_CHAIN_DRIVE / CH_SUB_ORCHESTRATOR.

These tests reconstruct the conductor and sub-orchestrator renders EXACTLY as
``inject_conductor_chain_drive`` assembles them (same builders, same ``"\\n\\n".join``
order), so they are pure — no DB, no module-level mutable state — and safe under
pytest-xdist -n auto.

SOLO IS SACRED: ``trim_embedded_protocol_for_chain`` is reached only from the injector,
which returns before any trim on the solo path (chain_ctx is None). The drift/no-op
tests pin that an unknown role and a missing-anchor protocol are returned unchanged.

Edition Scope: CE.
"""

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
# The single canonical advance-gate sentence (STEP B). It was repeated ~9x across the
# pre-BE-6214 drive prose; the lean render states it once and points elsewhere.
_CANONICAL_ADVANCE_SENTENCE = "that is the server's ONE authoritative"


def _solo_orchestrator_protocol(*, is_chain_conductor: bool) -> str:
    """The embedded ``full_protocol`` the injector receives for this role."""
    return _generate_orchestrator_protocol(
        job_id="job-6214",
        tenant_key="tk_6214",
        executor_id="exec-6214",
        execution_mode=_MODE,
        tool=_MODE,
        is_chain_conductor=is_chain_conductor,
    )


def _conductor_render() -> str:
    """Reconstruct the conductor branch of inject_conductor_chain_drive (parts order)."""
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    # BE-6215: the former CH_CONDUCTOR chapter is folded into CH_CHAIN_DRIVE — the
    # conductor render is CH_CAPABILITY + CH_CHAIN_DRIVE + trimmed-embedded only.
    # BE-9083a: chain chapters lead; the trimmed solo body trails (truncation-survival
    # reorder — mirrors inject_conductor_chain_drive's join order).
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
    """Reconstruct the sub-orchestrator branch of inject_conductor_chain_drive.

    BE-9083d: the injector is now phase-scoped; this reconstruction mirrors the
    IMPLEMENTATION-phase render (the band this file has always measured — the
    staging-phase render is pinned in test_be9083d_phase_scope_sections)."""
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=False)
    # BE-9083a: CH_SUB_ORCHESTRATOR leads; the trimmed solo body trails (mirrors
    # inject_conductor_chain_drive's join order).
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


# ---------------------------------------------------------------------------
# 1. Conductor INJECTOR-OUTPUT byte budget (regression guard, NOT the spec total)
#
# HONEST MEASUREMENT NOTE (BE-6214 audit). These bands measure the INJECTOR OUTPUT
# only = the trimmed embedded full_protocol + the appended chain chapters. They do
# NOT include the unchanged ~7.7 KB (conductor) / ~9.4 KB (sub-orch) agent_identity
# that ships in the same get_job_mission payload. So these numbers are a regression
# guard on the trim, NOT the spec's total-payload figure. The HONEST total-payload
# reduction (identity + protocol, the block the etag hashes) is:
#   conductor ~44.5 KB -> ~35.5 KB  (-20%)
#   sub-orch  ~33.8 KB -> ~30.6 KB  (-9%)
# The spec's ~67% / ~40% target is NOT met by this commit: it needed the deeper
# levers (merge CH_CONDUCTOR into CH_CHAIN_DRIVE down to ~9-10 KB + an aggressive
# lean conductor-identity rewrite) which carry real no-instruction-lost + guard-
# rewrite risk and are DEFERRED to a tracked follow-up (see closeout). Do NOT read
# the bands below as the spec/payload figure.
# ---------------------------------------------------------------------------


def test_conductor_render_is_lean_with_floor() -> None:
    """The conductor INJECTOR OUTPUT (trimmed embedded protocol + chain chapters) is
    meaningfully leaner than pre-BE-6214 (override-first preamble gone, embedded solo
    protocol trimmed) while staying ABOVE the irreducible floor: CH_CHAIN_DRIVE
    (~12.5 KB) + CH_CAPABILITY + CH_CONDUCTOR are load-bearing and sum to ~18 KB, so
    the conductor render cannot drop near the spec's ~15 KB without the deferred deep
    chapter-merge. The ceiling catches a regression back toward the pre-trim ~36 KB.
    This is the injector output, NOT the total payload (see the module note above)."""
    render_bytes = _b(_conductor_render())
    assert render_bytes >= 12_000, f"conductor render fell below the irreducible floor: {render_bytes}"
    # TSK-6232 re-tightened 26_800 -> 23_400: the CH_CHAIN_DRIVE prose diet (redundant-with-
    # scar-tissue cuts — GO gate/precedence/loop-"runs FREE" restatements collapsed, STEP A/B and
    # directive-relay asides pared to skeleton) dropped the render to 23_167. Tight bound just
    # above it. The residual is dominated by the 6.2 KB spawn_command (phase-critical OS x harness
    # runnable-command matrix from render_suborch_spawn_command) which is not chapter prose.
    assert render_bytes <= 23_400, f"conductor render regressed above the lean ceiling: {render_bytes}"


def test_conductor_embedded_trim_removes_meaningful_span() -> None:
    """The embedded-protocol trim actually fires and removes a meaningful span (the
    solo 3-phase region the chain chapters own) — proving the lean win is real, not a
    no-op that happens to fit the budget."""
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    trimmed = trim_embedded_protocol_for_chain(full_protocol, "conductor")
    assert _b(full_protocol) - _b(trimmed) >= 4_000, "conductor embedded trim must remove a meaningful span"


# ---------------------------------------------------------------------------
# 2. Sub-orch INJECTOR-OUTPUT byte band (regression guard, NOT the spec total)
#    Injector output only; the total payload adds the unchanged ~9.4 KB identity
#    (honest total ~33.8 KB -> ~30.6 KB, -9%). See the module note above §1.
# ---------------------------------------------------------------------------


def test_suborch_render_band() -> None:
    """The sub-orchestrator INJECTOR OUTPUT keeps PHASE 2 + the numbered closeout steps of
    the solo body, but BE-9083c now trims TWO spans (the PHASE-1 STARTUP ritual + the PHASE-3
    preamble), landing in the [19_500, 22_500] band — below the pre-BE-9083c ~23.4 KB output.
    (BE-9083a reordered the chapters ahead of the trimmed body; BE-9012d's Hub coordination
    calls are structurally longer than the retired bus reads.) This is injector output, NOT
    the total payload (which adds the unchanged ~9.4 KB identity); the chain_mission slice
    (item 1) shrinks the total further and scales with chain length — see test_be9083c."""
    render_bytes = _b(_suborch_render())
    assert render_bytes >= 19_500, f"sub-orch render fell below the band: {render_bytes}"
    assert render_bytes <= 22_500, f"sub-orch render regressed above the band: {render_bytes}"


# ---------------------------------------------------------------------------
# 3. Advance-gate stated once; drive TODO wording survives
# ---------------------------------------------------------------------------


def test_conductor_advance_gate_sentence_stated_once() -> None:
    """The canonical advance-gate sentence appears EXACTLY once in the full conductor
    render (it was repeated across the pre-BE-6214 drive/crash-resume/inbox prose);
    everywhere else points at STEP B instead of restating it."""
    render = _conductor_render()
    assert render.count(_CANONICAL_ADVANCE_SENTENCE) == 1, (
        f"canonical advance-gate sentence must appear exactly once, got {render.count(_CANONICAL_ADVANCE_SENTENCE)}"
    )


def test_conductor_drive_todo_wording_survives() -> None:
    """The conductor's emitted drive-TODO wording still matches CHAIN_DRIVE_TODO_PATTERN
    (poll / advance / series-summary / chain-finale / drive / conductor), so the closeout
    auto-ack of conductor drive TODOs keeps working after the lean trim."""
    from giljo_mcp.domain.todo_kinds import CHAIN_DRIVE_TODO_PATTERN  # BE-9012b: relocated

    render = _conductor_render()
    assert CHAIN_DRIVE_TODO_PATTERN.search(render), "lean conductor render must retain drive-TODO keyword wording"


# ---------------------------------------------------------------------------
# 4. Preamble markers gone; the 3 seams relocated into the chapters
# ---------------------------------------------------------------------------


def test_preamble_markers_absent_from_both_renders() -> None:
    """The override-first preamble markers are gone from BOTH role renders (the builders
    were deleted in BE-6214)."""
    conductor = _conductor_render()
    suborch = _suborch_render()
    for marker in ("CH_CONDUCTOR_PREAMBLE", "CH_SUBORCH_PREAMBLE"):
        assert marker not in conductor, f"{marker} must be absent from the conductor render"
        assert marker not in suborch, f"{marker} must be absent from the sub-orch render"


def test_three_seams_relocated_into_conductor_chapters() -> None:
    """Conductor seams now live in CH_CHAIN_DRIVE: handed scope (no continuation hunt),
    escalation sink via the Hub thread, and advance-not-complete_job."""
    render = _conductor_render()
    # Seam 1 — handed scope (suppress the solo continuation hunt).
    assert "SCOPE IS HANDED" in render
    assert "scan for a project to continue" in render
    # Seam 2 — escalation sink + Hub-thread discovery.
    # BE-9291 DELIBERATELY CHANGED this from `list_threads` to the FK discovery path.
    # In the CONDUCTOR render the bare name still appears 12 times — entirely inside the
    # sub-orch SPAWN COMMAND (launch_command_synth) — so the old assertion passed on spawn
    # boilerplate rather than on the escalation sink it claims to guard.
    assert "hub_thread_id" in render
    assert "ESCALATION" in render
    # Seam 3 — advance, not complete_job (server refuses a premature finale).
    assert "CONDUCTOR_CHAIN_INCOMPLETE" in render
    assert "ADVANCE" in render


def test_three_seams_relocated_into_suborch_chapter() -> None:
    """Sub-orch seams now live in CH_SUB_ORCHESTRATOR: handed scope, escalate to the
    conductor via the Hub, and closeout-is-the-handoff."""
    render = _suborch_render()
    assert "SCOPE IS HANDED" in render
    assert "scan for a project to continue" in render
    # BE-9291 DELIBERATELY CHANGED this from `list_threads` (now only the ToolSearch
    # bootstrap hint in this render) to the FK discovery path the sub-orch actually uses.
    assert "hub_thread_id" in render
    assert "write_project_closeout" in render


# ---------------------------------------------------------------------------
# 5. Graceful drift / role guards (no raise, return unchanged)
# ---------------------------------------------------------------------------


def test_trim_is_graceful_on_anchor_drift_and_unknown_role() -> None:
    """Missing anchors, an unknown role, and an empty protocol all return the input
    UNCHANGED (graceful no-op) — a future edit that moves the anchors degrades to the
    full embedded render rather than raising or corrupting the prose."""
    no_anchors = "a protocol with none of the BE-6214 trim anchors present"
    assert trim_embedded_protocol_for_chain(no_anchors, "conductor") == no_anchors
    assert trim_embedded_protocol_for_chain(no_anchors, "sub_orchestrator") == no_anchors

    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    # Unknown role → unchanged (solo / any non-chain role never trims).
    assert trim_embedded_protocol_for_chain(full_protocol, "solo") == full_protocol
    assert trim_embedded_protocol_for_chain(full_protocol, "worker") == full_protocol
    # Empty / falsy protocol → returned as-is.
    assert trim_embedded_protocol_for_chain("", "conductor") == ""


# ---------------------------------------------------------------------------
# 6. Reverse-splice lock — the trim removes EXACTLY the anchored span, nothing else
# ---------------------------------------------------------------------------


def test_conductor_reverse_splice_lock() -> None:
    """Splicing the excised span back into the trimmed conductor protocol reproduces the
    original full_protocol byte-for-byte — proving the trim removed EXACTLY the anchored
    region (from _CHAIN_PROTOCOL_REGION_START up to _CHAIN_PROTOCOL_REGION_END) and
    nothing else, and that the kept tail is byte-identical."""
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=True)
    trimmed = trim_embedded_protocol_for_chain(full_protocol, "conductor")
    start = full_protocol.find(_CHAIN_PROTOCOL_REGION_START)
    end = full_protocol.find(_CHAIN_PROTOCOL_REGION_END)
    excised = full_protocol[start:end]
    reconstructed = trimmed.replace(_CONDUCTOR_EMBEDDED_NOTE, excised, 1)
    assert reconstructed == full_protocol, "reverse-splice must reproduce the original conductor protocol exactly"


def test_suborch_reverse_splice_lock() -> None:
    """Splicing BOTH excised sub-orch spans back into the trimmed protocol reproduces the
    original full_protocol byte-for-byte — proving each cut (BE-9083c PHASE-1 STARTUP +
    the BE-6214 PHASE-3 preamble) removed EXACTLY its anchored span and every kept region
    is byte-identical."""
    full_protocol = _solo_orchestrator_protocol(is_chain_conductor=False)
    trimmed = trim_embedded_protocol_for_chain(full_protocol, "sub_orchestrator")
    p1_excised = full_protocol[full_protocol.find(_SUBORCH_PHASE1_START) : full_protocol.find(_SUBORCH_PHASE1_END)]
    p3_excised = full_protocol[full_protocol.find(_SUBORCH_PHASE3_START) : full_protocol.find(_SUBORCH_PHASE3_END)]
    reconstructed = trimmed.replace(_SUBORCH_PHASE1_NOTE, p1_excised, 1).replace(_SUBORCH_PHASE3_NOTE, p3_excised, 1)
    assert reconstructed == full_protocol, "reverse-splice must reproduce the original sub-orch protocol exactly"
