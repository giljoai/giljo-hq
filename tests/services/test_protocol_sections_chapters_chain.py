# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import uuid



_COMMON_ARGS = {
    "cli_mode": True,
    "project_id": "proj-chain-test",
    "orchestrator_id": "job-chain-test",
    "tenant_key": "tk_chain_test",
    "include_implementation_reference": False,
}

_CHAIN_CHAPTERS = frozenset({"ch_capability", "ch_chain_staging", "ch_chain_drive"})


def _make_chain_ctx(
    *,
    role: str = "conductor",
    is_staging: bool = True,
    resolved_order: list[str] | None = None,
    conductor_agent_id: str | None = None,
    execution_mode: str = "multi_terminal",
):
    from giljo_mcp.services.sequence_chain_context import ChainContext

    return ChainContext(
        run_id=str(uuid.uuid4()),
        role=role,
        current_index=0,
        resolved_order=resolved_order or [str(uuid.uuid4()), str(uuid.uuid4())],
        is_staging=is_staging,
        conductor_agent_id=conductor_agent_id or str(uuid.uuid4()),
        execution_mode=execution_mode,
    )


def _build(**kwargs):
    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    return _build_orchestrator_protocol(**_COMMON_ARGS, **kwargs)




def test_conductor_staging_emits_staging_and_capability_not_drive() -> None:
    conductor_id = str(uuid.uuid4())
    ctx = _make_chain_ctx(role="conductor", is_staging=True, conductor_agent_id=conductor_id)
    result = _build(chain_ctx=ctx, conductor_agent_id=conductor_id)

    assert "ch_capability" in result, "Conductor at staging must include ch_capability"
    assert "ch_chain_staging" in result, "Conductor at staging must include ch_chain_staging"
    assert "ch_chain_drive" not in result, "ch_chain_drive must NOT appear at staging phase"

    assert "ch_conductor" not in result, "ch_conductor must NOT render during staging (phase-gated, B1)"

    assert ctx.run_id in result["ch_chain_staging"], "run_id must appear in CH_CHAIN_STAGING"
    assert f"{len(ctx.resolved_order)}-project" in result["ch_chain_staging"], (
        "Project count must appear in CH_CHAIN_STAGING"
    )




def test_conductor_implementation_emits_drive_and_capability_not_staging() -> None:
    conductor_id = str(uuid.uuid4())
    ctx = _make_chain_ctx(role="conductor", is_staging=False, conductor_agent_id=conductor_id)
    result = _build(chain_ctx=ctx, conductor_agent_id=conductor_id)

    assert "ch_capability" in result, "Conductor at implementation must include ch_capability"
    assert "ch_chain_drive" in result, "Conductor at implementation must include ch_chain_drive"
    assert "ch_chain_staging" not in result, "ch_chain_staging must NOT appear at implementation phase"
    assert "ch_conductor" not in result, "BE-6215: ch_conductor is folded into ch_chain_drive (no separate key)"
    assert "YOU ARE ADDRESSABLE: USER DIRECTIVE RELAY" in result["ch_chain_drive"], (
        "the folded directive-relay protocol must render inside ch_chain_drive"
    )

    assert ctx.run_id in result["ch_chain_drive"], "run_id must appear in CH_CHAIN_DRIVE"
    assert "TERMINATE_CHAIN" not in result["ch_chain_drive"], (
        "BE-6186: the inert TERMINATE_CHAIN clause must be gone from CH_CHAIN_DRIVE"
    )


def test_conductor_generic_mcp_drive_uses_placeholder_not_validated_claude() -> None:
    conductor_id = str(uuid.uuid4())
    ctx = _make_chain_ctx(
        role="conductor", is_staging=False, conductor_agent_id=conductor_id, execution_mode="generic_mcp"
    )
    drive = _build(chain_ctx=ctx, conductor_agent_id=conductor_id)["ch_chain_drive"]

    assert "<your-harness>" in drive, "generic_mcp STEP A must carry the self-substitution placeholder"
    assert "VALIDATED" not in drive, "the [claude | VALIDATED] tag must not reach a generic_mcp conductor"
    assert "[claude" not in drive, "no per-harness claude launch line for a generic_mcp conductor"
    assert "cmd /k <your-harness> --prompt" in drive, "Windows launch is the BE-9015 `cmd /k` form"




def test_solo_path_byte_identical_to_no_chain_ctx() -> None:
    baseline = _build()
    explicit_none = _build(chain_ctx=None)

    assert baseline == explicit_none, "Passing chain_ctx=None must produce byte-identical output to omitting it"

    for ch in _CHAIN_CHAPTERS:
        assert ch not in baseline, f"{ch} must not appear in solo (no-chain) output"




def test_sub_orchestrator_emits_no_chain_chapters() -> None:
    ctx = _make_chain_ctx(role="sub_orchestrator", is_staging=False)
    result = _build(chain_ctx=ctx)

    for ch in _CHAIN_CHAPTERS:
        assert ch not in result, f"sub_orchestrator must NOT emit {ch}"




def test_ch_capability_multi_terminal_branch() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_capability

    cap = _build_ch_capability(execution_mode="multi_terminal")

    assert "EXECUTION MODE = multi_terminal" in cap, "must state the resolved mode as fact"
    assert "IMMUTABLE" in cap, "must state the mode is immutable"
    assert "GUARANTEED" in cap, "multi_terminal context isolation is guaranteed"
    assert "FAIL LOUD" in cap, "fail-loud fallback must replace the silent downgrade"
    assert "VERIFY" not in cap, "BE-6182: the runtime terminal self-probe is removed"
    assert "try to spawn" not in cap.lower(), "BE-6182: no 'try to spawn a terminal' probe"


def test_ch_capability_subagent_mode_isolation_is_best_effort() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_capability

    cap = _build_ch_capability(execution_mode="claude_code_cli")
    low = cap.lower()

    assert "claude_code_cli" in cap, "must name the resolved subagent mode"
    assert "fresh" in low and "terminal" in low, "sub-orch spawn must be a fresh terminal"
    assert "GUARANTEED" in cap, "BE-6205: fresh-terminal sub-orch isolation IS guaranteed"
    assert "REAL Task()" in cap, "Task() is the sub-orch's WORKER mechanism in a subagent mode"
    assert "WORKER" in cap, "the Task() form is scoped to WORKERS, not sub-orch spawning"
    assert "BEST-EFFORT" in cap, "worker isolation must be worded as best-effort"
    assert "run each p_i as a real task()" not in low, "the reversed sub-orch-spawn-via-Task() language must be gone"
    assert "inline" in low, "must forbid running work inline"


def test_ch_capability_is_a_contract_not_a_probe() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_capability

    for mode in ("multi_terminal", "claude_code_cli", "codex_cli"):
        cap = _build_ch_capability(execution_mode=mode)
        assert "CONTRACT" in cap, f"{mode}: must render as a contract"
        assert "no per-project gate" in cap.lower(), f"{mode}: must state there is NO per-project gate"
        assert "launch_implementation" not in cap.lower(), f"{mode}: gateless — launch_implementation must be gone"
        assert "staging_complete" not in cap.lower(), f"{mode}: gateless — staging_complete wait must be gone"
        assert "re-probe" in cap.lower() or "do not re-probe" in cap.lower(), (
            f"{mode}: must instruct NOT to re-probe the harness"
        )
        assert "never silently switch modes" in cap.lower(), f"{mode}: must forbid self-switching modes"
        assert "if unsure" not in cap.lower(), f"{mode}: the old 'if unsure' downgrade tree must be gone"


def test_conductor_ch_capability_present_for_mode() -> None:
    from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol

    ctx = _make_chain_ctx(role="conductor", is_staging=True)
    result = _build_orchestrator_protocol(
        cli_mode=False,
        project_id="proj-chain-mode-test",
        orchestrator_id="job-chain-mode-test",
        tenant_key="tk_chain_mode",
        include_implementation_reference=False,
        tool="multi_terminal",
        chain_ctx=ctx,
    )
    cap = result.get("ch_capability", "")
    assert cap, "ch_capability must be present for a conductor"
    assert "EXECUTION MODE = multi_terminal" in cap, (
        f"Assembler must render the multi_terminal contract; got: {cap[:300]!r}"
    )




def test_platform_registry_can_spawn_terminals_all_rows() -> None:
    from giljo_mcp.platform_registry import MODES

    assert len(MODES) == 2, f"Expected 2 registered modes, got {len(MODES)}"
    by_mode = {m.execution_mode: m for m in MODES}
    assert by_mode["multi_terminal"].can_spawn_terminals is True, (
        "multi_terminal is intrinsically terminal-capable (a human opens a terminal per agent)"
    )
    assert by_mode["subagent"].can_spawn_terminals is False, (
        "subagent terminal ability is a runtime session property, never assumed from the mode"
    )


def test_terminal_capable_modes_populated() -> None:
    from giljo_mcp.platform_registry import TERMINAL_CAPABLE_MODES, VALID_EXECUTION_MODES

    assert isinstance(TERMINAL_CAPABLE_MODES, frozenset), "TERMINAL_CAPABLE_MODES must be a frozenset"
    assert {"multi_terminal"} == TERMINAL_CAPABLE_MODES, (
        f"only multi_terminal is intrinsically terminal-capable, got {TERMINAL_CAPABLE_MODES}"
    )
    assert VALID_EXECUTION_MODES - {"subagent"} == TERMINAL_CAPABLE_MODES, (
        "subagent (BE-9035c generalizes the old generic_mcp opt-out to the whole mode) is the "
        "one valid mode absent from TERMINAL_CAPABLE_MODES"
    )




def test_valid_execution_modes_same_object() -> None:
    import giljo_mcp.models.sequence_runs as sr_module
    import giljo_mcp.platform_registry as pr_module

    assert sr_module.VALID_EXECUTION_MODES is pr_module.VALID_EXECUTION_MODES, (
        "sequence_runs.VALID_EXECUTION_MODES must be the SAME object as "
        "platform_registry.VALID_EXECUTION_MODES (imported, not re-declared)"
    )
    assert frozenset({"multi_terminal", "subagent"}) == sr_module.VALID_EXECUTION_MODES, (
        "BE-9035c: VALID_EXECUTION_MODES must contain exactly the 2 canonical execution modes"
    )




def test_conductor_staging_does_not_pollute_solo_render() -> None:
    solo = _build()
    conductor_id = str(uuid.uuid4())
    ctx = _make_chain_ctx(role="conductor", is_staging=True, conductor_agent_id=conductor_id)
    conductor = _build(chain_ctx=ctx, conductor_agent_id=conductor_id)

    for ch in _CHAIN_CHAPTERS:
        assert ch not in solo, f"{ch} leaked into solo render"
    assert "ch_chain_staging" in conductor

    for core_ch in ("ch1_your_mission", "ch2_startup_sequence", "ch3_agent_spawning_rules"):
        assert core_ch in solo
        assert core_ch in conductor




def test_chain_staging_emits_short_mode_token_not_execution_mode() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-x",
        resolved_order=["head", "p2"],
        execution_mode="claude_code_cli",
        job_id="job-x",
    )
    assert 'mode="claude"' in chapter, "must emit the short stage mode token"
    assert "claude_code_cli" not in chapter, "must NOT leak the execution_mode vocabulary into stage_project"
    assert 'execution_mode="' not in chapter, "must NOT call stage_project with the execution_mode= param"


def test_chain_staging_states_complete_job_is_last_and_stages_all() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-x", resolved_order=["head", "p2", "p3"], execution_mode="claude_code_cli", job_id="job-77"
    )
    low = chapter.lower()
    assert "complete_job" in low and "last" in low, "must state complete_job is the LAST call"
    assert "job-77" in chapter, "the real conductor job_id must appear"
    assert "every project" in low, "must describe staging EVERY project symmetrically"


def test_chain_drive_threads_real_job_id() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive

    chapter = _build_ch_chain_drive(
        run_id="run-x",
        resolved_order=["head", "p2"],
        current_index=0,
        execution_mode="claude_code_cli",
        conductor_agent_id="cond-1",
        job_id="job-real-99",
    )
    assert "job-real-99" in chapter, "real job_id must be threaded into progress/closeout calls"
    assert "<your job_id>" not in chapter, "the placeholder must be replaced"


def test_ch_capability_probe_removed() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_capability

    cap = _build_ch_capability(execution_mode="claude_code_cli")
    assert "CAN YOU OPEN AN INDEPENDENT OS TERMINAL" not in cap, "the runtime probe must be gone"
    assert "RE-STAGE" in cap, "fail-loud fallback must instruct re-staging"


def test_conductor_implementation_emits_conductor_chapter() -> None:
    conductor_id = str(uuid.uuid4())
    ctx = _make_chain_ctx(role="conductor", is_staging=False, conductor_agent_id=conductor_id)
    result = _build(chain_ctx=ctx, conductor_agent_id=conductor_id)
    assert "ch_conductor" not in result, "BE-6215: no separate ch_conductor chapter (folded)"
    drive = result["ch_chain_drive"]
    assert "YOU ARE ADDRESSABLE: USER DIRECTIVE RELAY" in drive, "directive-relay protocol must live in ch_chain_drive"
    assert "DIRECTIVE RELAY" in drive and "NO WORKER-PROTOCOL FORK" in drive, "relay + no-worker-fork must survive"
    assert conductor_id in drive, "the conductor's agent_id must be embedded in the drive chapter"




def test_chain_staging_head_is_symmetric_not_special() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-x", resolved_order=["head-pid", "p2"], execution_mode="multi_terminal", job_id="job-x"
    )
    low = chapter.lower()
    assert "already staged" not in low, "BE-6186: the dual-hat 'head already staged' language must be gone"
    assert "symmetric" in low, "must state the head is symmetric with the rest"
    assert "head-pid" in chapter, "the head project id must appear in the run order"


def test_chain_staging_spawns_no_agents_and_stages_every_project() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-x", resolved_order=["head", "p2"], execution_mode="multi_terminal", job_id="job-x"
    )
    low = chapter.lower()
    assert "two-phase" not in low, "BE-6186: the head agent-spawn (two-phase) prose must be gone"
    assert "mission-less" not in low, "BE-6186: no mission-less agent-spawn for the conductor"
    assert "spawn no agents" in low, "the conductor must be told to spawn NO agents"
    assert "stage_project" in chapter, "the conductor stages each project's sub-orchestrator"
    assert 'update_job_mission(job_id="job-x"' in chapter, "chain mission is written to the conductor's own job"


def test_chain_staging_writes_chain_mission_to_own_job_not_head_project() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-x", resolved_order=["head-pid", "p2"], execution_mode="multi_terminal", job_id="job-77"
    )
    assert "job-77" in chapter, "the conductor's own job_id must appear"
    assert 'update_job_mission(job_id="job-77"' in chapter, "chain mission goes to update_job_mission on own job"
    assert 'update_project_mission(project_id="head-pid", mission=<chain' not in chapter, (
        "BE-6186: the chain mission must NOT be written onto the head project"
    )




def test_chain_drive_phase3_closeout_line_carries_override_adjacent() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive

    chapter = _build_ch_chain_drive(
        run_id="run-x",
        resolved_order=["head", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id="cond-1",
        job_id="job-real-99",
    )

    quote = "complete_job your\norchestrator job"
    idx = chapter.find(quote)
    assert idx != -1, "the solo PHASE 3 closeout line must be quoted so it can be explicitly overridden"

    window = chapter[max(0, idx - 200) : idx + 200].lower()
    assert "does not apply" in window or "overridden" in window, (
        "the quoted PHASE 3 closeout line must have override framing adjacent"
    )


def test_chain_drive_override_precedes_series_summary_completion() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive

    chapter = _build_ch_chain_drive(
        run_id="run-x",
        resolved_order=["head", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id="cond-1",
        job_id="job-real-99",
    )
    low = chapter.lower()
    override_idx = low.find("conductor precedence")
    summary_idx = low.find("series summary")
    assert 0 <= override_idx < summary_idx, "the override must be front-loaded, ahead of the SERIES SUMMARY finale"
    assert "do not call complete_job" in low, "the override must explicitly forbid an early conductor complete_job"




def _suborch(execution_mode: str = "multi_terminal"):
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_sub_orchestrator

    return _build_ch_sub_orchestrator(
        run_id="run-x",
        position=2,
        n_projects=3,
        execution_mode=execution_mode,
    )


def _suborch_step7(text: str) -> str:
    start = text.find("7. CLOSE OUT")
    assert start != -1, "CH_SUB_ORCHESTRATOR must contain a step 7 (CLOSE OUT)"
    return text[start:]


def test_suborch_step7_complete_job_before_write_project_closeout() -> None:
    step7 = _suborch_step7(_suborch())

    cj = step7.find("complete_job")
    wpc = step7.find("write_project_closeout")
    assert cj != -1, "step 7 must name complete_job"
    assert wpc != -1, "step 7 must name write_project_closeout"
    assert cj < wpc, (
        "complete_job must come BEFORE write_project_closeout in step 7 (server-enforced "
        "readiness gate); the inverse raises COMPLETION_BLOCKED and stalls the chain"
    )


def test_suborch_step7_is_mode_agnostic_byte_identical() -> None:
    assert _suborch_step7(_suborch("multi_terminal")) == _suborch_step7(_suborch("claude_code_cli")), (
        "step 7 must be byte-identical across execution modes (mode-agnostic closeout)"
    )




def test_chain_staging_halts_for_user_go_after_staging() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_staging

    chapter = _build_ch_chain_staging(
        run_id="run-go", resolved_order=["p1", "p2"], execution_mode="multi_terminal", job_id="job-go"
    )
    low = chapter.lower()
    assert "halt after staging" in low, "the staging chapter must firmly HALT after staging"
    assert "explicit go" in low, "must require the user's EXPLICIT GO"
    assert "implement chain" in low, "must name the dashboard GO equivalent"
    assert "do not re-call get_job_mission" in low, "must forbid self-driving via get_job_mission"
    assert "do not drive" in low, "must forbid driving before the GO"
    assert "do not spawn any sub-orchestrator" in low, "must forbid spawning before the GO"


def test_chain_drive_proceeds_only_after_user_go() -> None:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive

    chapter = _build_ch_chain_drive(
        run_id="run-go",
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode="multi_terminal",
        conductor_agent_id="cond-go",
        job_id="job-go",
    )
    low = chapter.lower()
    assert "proceed only after the user's explicit go" in low, "the drive chapter must gate on the user's GO"
    assert "not cleared to drive" in low, "must state the conductor is not cleared to drive without the GO"


_BE6221E_GO_GATE_STRINGS = (
    "HALT AFTER STAGING",
    "WAIT FOR THE USER'S EXPLICIT GO",
    "PROCEED ONLY AFTER THE USER'S EXPLICIT GO",
)


def test_be6221e_go_gate_prose_absent_from_solo_render() -> None:
    solo = _build()
    blob = "\n".join(str(v) for v in solo.values())
    for needle in _BE6221E_GO_GATE_STRINGS:
        assert needle not in blob, f"BE-6221e chain-only GO-gate prose leaked into the solo render: {needle!r}"



_BE9626_MARKERS = (
    "NATIVE HARNESS NUDGE",
    "session-to-session",
    "best-effort",
    "ListAgents",
    "codex queue",
)


def _drive_chapter(execution_mode: str) -> str:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_chain_drive

    return _build_ch_chain_drive(
        run_id="run-9626",
        resolved_order=["p1", "p2"],
        current_index=0,
        execution_mode=execution_mode,
        conductor_agent_id="cond-9626",
        job_id="job-9626",
    )


def _suborch_chapter(execution_mode: str, phase: str | None = None) -> str:
    from giljo_mcp.services.protocol_sections.chapters_chain import _build_ch_sub_orchestrator

    return _build_ch_sub_orchestrator(
        run_id="run-9626",
        position=2,
        n_projects=3,
        execution_mode=execution_mode,
        phase=phase,
    )


def test_be9626_nudge_block_renders_for_multi_terminal_conductor() -> None:
    chapter = _drive_chapter("multi_terminal")
    for needle in _BE9626_MARKERS:
        assert needle in chapter, f"multi_terminal conductor render is missing the nudge marker {needle!r}"


def test_be9626_nudge_is_an_addition_to_the_hub_never_a_replacement() -> None:
    flat = " ".join(_drive_chapter("multi_terminal").split()).lower()
    assert "in addition to the hub" in flat, "the nudge must be framed as an addition to the Hub"
    assert "never instead of it" in flat, "the nudge must never replace the Hub"
    assert "unacknowledged" in flat, "a nudge must be treated as unacknowledged"
    assert "re-discover" in flat, "the peer address must be re-discovered before every send"
    assert "required to read" in flat, "the Hub must stay the only channel every participant must read"
    assert "ground truth" in flat, "the Hub must stay the ground truth for run state"


def test_be9626_hub_lines_survive_in_the_multi_terminal_conductor_render() -> None:
    chapter = _drive_chapter("multi_terminal")
    for needle in ("hub_thread_id", "get_thread_history", "unread_only=true", "mark_read=true", "ESCALATION SINK"):
        assert needle in chapter, f"existing Hub prose lost on the multi_terminal render: {needle!r}"


def test_be9626_no_worker_protocol_fork_is_reconciled() -> None:
    chapter = _drive_chapter("multi_terminal")
    start = chapter.find("NO WORKER-PROTOCOL FORK")
    assert start != -1, "the NO WORKER-PROTOCOL FORK clause must still render"
    flat = " ".join(chapter[start:].split()).lower()
    assert "not a fork" in flat, "the fork clause must state the nudge is not a protocol fork"


def test_be9626_nudge_absent_from_subagent_conductor_render() -> None:
    chapter = _drive_chapter("subagent")
    for needle in _BE9626_MARKERS:
        assert needle not in chapter, f"nudge prose leaked into the subagent conductor render: {needle!r}"


def test_be9626_nudge_block_renders_for_multi_terminal_suborch_both_phases() -> None:
    for phase in (None, "staging", "implementation"):
        chapter = _suborch_chapter("multi_terminal", phase)
        for needle in _BE9626_MARKERS:
            assert needle in chapter, f"sub-orch render (phase={phase}) is missing the nudge marker {needle!r}"
        assert "hub_thread_id" in chapter, f"sub-orch render (phase={phase}) lost its Hub prose"


def test_be9626_nudge_absent_from_subagent_suborch_render() -> None:
    for phase in (None, "implementation"):
        chapter = _suborch_chapter("subagent", phase)
        for needle in _BE9626_MARKERS:
            assert needle not in chapter, f"nudge prose leaked into the subagent sub-orch render (phase={phase})"


def test_be9626_nudge_prose_absent_from_solo_render() -> None:
    solo = _build()
    blob = "\n".join(str(v) for v in solo.values())
    for needle in _BE9626_MARKERS:
        assert needle not in blob, f"BE-9626 chain-only nudge prose leaked into the solo render: {needle!r}"


def test_be9626_guide_chain_section_states_the_rule() -> None:
    from giljo_mcp.tools.giljo_guide import build_giljo_guide

    flat = " ".join(build_giljo_guide()["guide"].split()).lower()
    assert "message hub" in flat
    assert "nudge" in flat, "the guide's chain section must describe the optional native nudge"
    assert "never instead of it" in flat, "the guide must state the Hub is never replaced"
