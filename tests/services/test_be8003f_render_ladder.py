# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

import giljo_mcp.prompts.launch_command_synth as lcs
from giljo_mcp.platform_registry import (
    EXECUTION_MODES,
    PLATFORM_PRESETS,
    PRESET_NAMES,
    get_preset,
)
from giljo_mcp.prompts.multi_terminal_prompt_builder import MultiTerminalPromptBuilder
from giljo_mcp.services.mission_assembly import assemble_mission_context
from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol
from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_drive,
    _build_chain_drive_step_a,
)
from giljo_mcp.services.protocol_sections.orchestrator_body import (
    render_capability_ladder,
    trim_embedded_protocol_for_chain,
)


_FIXTURE = Path(__file__).with_name("_be8003f_render_goldens.json")

_RUN_ID = "RUN-GOLD-0000"
_ORDER = ["P1-0000-0000", "P2-0000-0000", "P3-0000-0000"]
_JOB = "JOB-0000-0000"
_TENANT = "TENANT-GOLD"
_EXEC = "EXEC-0000-0000"
_COND = "COND-0000-0000"

_SUBAGENT_HARNESSES: tuple[str, ...] = ("claude-code", "codex", "opencode", "generic")


def _stub_jobs() -> list[SimpleNamespace]:
    return [
        SimpleNamespace(agent_display_name="ui-impl", job_id="AJ-1", cli_tool="claude"),
        SimpleNamespace(agent_display_name="be-impl", job_id="AJ-2", cli_tool="codex"),
        SimpleNamespace(agent_display_name="doc", job_id="AJ-3", cli_tool=None),
    ]


def _stub_project() -> SimpleNamespace:
    return SimpleNamespace(
        id="PROJ-0000",
        name="Golden Project",
        project_type_id=None,
        series_number=None,
        taxonomy_alias="",
    )


def _render_goldens() -> dict[str, str]:
    with mock.patch.object(lcs, "_pwsh_available", return_value=True):
        return _render_goldens_unpinned()


def _render_goldens_unpinned() -> dict[str, str]:
    cases: dict[str, str] = {}
    builder = MultiTerminalPromptBuilder()

    for mode in (None, *EXECUTION_MODES):
        cases[f"s1_capability::{mode}"] = _build_ch_capability(mode)
    for mode in EXECUTION_MODES:
        cases[f"s1_chain_drive::{mode}"] = _build_ch_chain_drive(
            run_id=_RUN_ID,
            resolved_order=_ORDER,
            current_index=0,
            execution_mode=mode,
            conductor_agent_id=_COND,
            job_id=_JOB,
        )
    cases["s1_step_a"] = _build_chain_drive_step_a(_RUN_ID, "<<SPAWN_COMMAND_PLACEHOLDER>>")

    for tool in ("claude-code", "multi_terminal", "codex"):
        cases[f"s2_seed_block::{tool}"] = builder._build_agent_seed_block(_stub_jobs(), tool)
        cases[f"s2_seed_block_empty::{tool}"] = builder._build_agent_seed_block([], tool)
    for tool in ("claude-code", "multi_terminal"):
        cases[f"s2_exec_prompt::{tool}"] = builder.build_execution_prompt(
            orchestrator_id="ORCH-0000",
            project=_stub_project(),
            agent_jobs=_stub_jobs(),
            git_enabled=True,
            tool=tool,
        )

    for cond in (False, True):
        cases[f"s3_orch::multi_terminal::conductor={cond}"] = _generate_orchestrator_protocol(
            _JOB, _TENANT, _EXEC, execution_mode="multi_terminal", tool="multi_terminal", is_chain_conductor=cond
        )
    for harness in _SUBAGENT_HARNESSES:
        for cond in (False, True):
            cases[f"s3_orch::subagent::{harness}::conductor={cond}"] = _generate_orchestrator_protocol(
                _JOB, _TENANT, _EXEC, execution_mode="subagent", tool=harness, is_chain_conductor=cond
            )

    def _worker(execution_mode: str, tool: str, git: bool) -> str:
        return _generate_agent_protocol(
            _JOB,
            _TENANT,
            "implementer",
            agent_id=_EXEC,
            execution_mode=execution_mode,
            git_integration_enabled=git,
            job_type="implementer",
            tool=tool,
            comm_thread_id="comm-thread-golden",
        )

    for git in (False, True):
        cases[f"s4_worker::multi_terminal::git={git}"] = _worker("multi_terminal", "multi_terminal", git)
    for harness in _SUBAGENT_HARNESSES:
        for git in (False, True):
            cases[f"s4_worker::subagent::{harness}::git={git}"] = _worker("subagent", harness, git)

    return cases


def _load_fixture() -> dict[str, str]:
    if not _FIXTURE.exists():  # pragma: no cover - guard for a missing committed fixture
        raise AssertionError(
            f"Golden fixture missing: {_FIXTURE}. Regenerate with `python {Path(__file__).name} --write` and commit it."
        )
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def test_s1_s4_render_byte_identical_on_none_path():
    golden = _load_fixture()
    current = _render_goldens()

    assert set(current) == set(golden), (
        f"case-set drift: added={sorted(set(current) - set(golden))} removed={sorted(set(golden) - set(current))}"
    )
    mismatches = [key for key in golden if current[key] != golden[key]]
    assert not mismatches, f"byte-identity BROKE on the None/CLI path for: {mismatches}"


@pytest.mark.parametrize("key", sorted(_render_goldens()))
def test_each_site_present_and_nonempty(key):
    value = _render_goldens()[key]
    if key.startswith("s2_seed_block_empty::"):
        assert value == ""
    else:
        assert value.strip(), f"empty render for {key}"



_PRESETS = list(PRESET_NAMES)
_S1_GATED = ("wt -w 0", "gnome-terminal", "osascript", "$DISPLAY", "$WAYLAND_DISPLAY")
_FLOOR = "[FLOOR]"
_INLINE = "INLINE CONDUCTING"


def test_render_capability_ladder_shape():
    out = render_capability_ladder("PREF", "FALL", "do X yourself", preset_display="Chat")
    assert out == (
        "[YOUR PATH — Chat]\n"
        "PREF\n"
        "[IF YOU CANNOT DO THE ABOVE]\n"
        "FALL\n"
        "[FLOOR] If none of the above works in your environment: post_to_thread on your "
        "coordination thread stating exactly what you cannot do, and show the user this "
        'line verbatim: "do X yourself".'
    )
    assert render_capability_ladder("P", "F", "L").startswith("[YOUR PATH]\n")


def test_platform_has_shell_matches_workspace_model():
    by_name = {p.execution_mode: p for p in PLATFORM_PRESETS}
    assert by_name["web_sandbox"].has_shell is True
    assert by_name["desktop_app"].has_shell is True
    assert by_name["chat"].has_shell is False
    for p in PLATFORM_PRESETS:
        assert p.has_shell == (p.workspace_model != "none")


@pytest.mark.parametrize("preset_name", _PRESETS)
def test_s1_capability_preset_drops_terminal_markers(preset_name):
    preset = get_preset(preset_name)
    out = _build_ch_capability("multi_terminal", preset=preset)
    for marker in _S1_GATED:
        assert marker not in out, f"S1 capability[{preset_name}] leaked {marker!r}"
    assert _FLOOR in out
    assert _INLINE in out
    assert preset.display_label in out


@pytest.mark.parametrize("preset_name", _PRESETS)
def test_s1_step_a_and_chain_drive_preset_drop_terminal_markers(preset_name):
    preset = get_preset(preset_name)
    step_a = _build_chain_drive_step_a("RUN-X", "IGNORED-SPAWN", preset=preset)
    drive = _build_ch_chain_drive("RUN-X", ["P1", "P2"], 0, "multi_terminal", "COND", "JOB", preset=preset)
    for out, label in ((step_a, "step_a"), (drive, "chain_drive")):
        for marker in _S1_GATED:
            assert marker not in out, f"S1 {label}[{preset_name}] leaked {marker!r}"
        assert _INLINE in out, f"S1 {label}[{preset_name}] missing inline-conducting marker"
    assert _FLOOR in step_a


@pytest.mark.parametrize("preset_name", _PRESETS)
def test_s2_seed_block_preset_is_session_worded_with_floor(preset_name):
    preset = get_preset(preset_name)
    jobs = [SimpleNamespace(agent_display_name="ui", job_id="J1", cli_tool="claude")]
    out = MultiTerminalPromptBuilder()._build_agent_seed_block(jobs, "multi_terminal", preset=preset)
    assert _FLOOR in out
    assert "## PER-SESSION AGENT SEED" in out
    assert "NEW SESSION" in out
    assert "## PER-TERMINAL AGENT SEED" not in out
    assert "as the CLI\nprompt" not in out
    assert "### Terminal:" not in out
    if not preset.has_shell:
        assert "code-WRITING job needs a session" in out


@pytest.mark.parametrize("preset_name", _PRESETS)
def test_s3_orchestrator_preset_has_waiting_ladder(preset_name):
    preset = get_preset(preset_name)
    out = _generate_orchestrator_protocol(
        "J", "T", "E", execution_mode="multi_terminal", tool="multi_terminal", preset=preset
    )
    assert _FLOOR in out
    assert "COORDINATING FROM A" in out
    for marker in ("ToolSearch", "TodoWrite", "sleep 1 "):
        assert marker not in out, f"S3 orchestrator[{preset_name}] leaked {marker!r}"


@pytest.mark.parametrize("preset_name", _PRESETS)
def test_s4_worker_shell_asides_gated_on_has_shell(preset_name):
    preset = get_preset(preset_name)
    out = _generate_agent_protocol(
        "J",
        "T",
        "impl",
        agent_id="E",
        execution_mode="multi_terminal",
        job_type="implementer",
        tool="multi_terminal",
        preset=preset,
    )
    if preset.has_shell:
        assert "ENVIRONMENT DETECTION" in out
        assert "sleep 1 " not in out
    else:
        assert "ENVIRONMENT DETECTION" not in out
        assert "Start-Sleep -Seconds N" not in out
        assert _FLOOR in out
        assert "NO SHELL (chat session)" in out


_CONDUCTOR_CLI_ONLY = ("SUB-ORCH SPAWN", "sleep 1 60", "Start-Sleep", "wait_seconds=45", "CH6")


def _conductor_runtime_render(preset_name: str | None) -> str:
    preset = get_preset(preset_name) if preset_name else None
    job = SimpleNamespace(project_id=None, job_type="orchestrator", job_id="JOB", mission="", created_at=None)
    execution = SimpleNamespace(
        agent_id="COND",
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        spawned_by=None,
        status="working",
        started_at=None,
        project_phase=None,
    )
    response = assemble_mission_context(
        mock.Mock(),
        job=job,
        execution=execution,
        project=None,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={"JOB": ""},
        current_team_state=None,
        tenant_key="T",
        integrations={},
        chain_execution_mode="multi_terminal",
        preset=preset,
        detected_harness="claude-code",
        checkin_cadence_minutes=10,
    )
    return "\n\n".join(
        [
            _build_ch_capability("subagent", preset=preset),
            _build_ch_chain_drive(
                "RUN-X", ["P1", "P2"], 0, "subagent", "COND", "JOB", preset=preset, detected_harness="claude-code"
            ),
            trim_embedded_protocol_for_chain(response.full_protocol, "conductor"),
        ]
    )


@pytest.mark.parametrize("preset_name", _PRESETS)
def test_conductor_runtime_preset_render_carries_no_cli_only_instruction(preset_name):
    out = _conductor_runtime_render(preset_name)
    leaked = [marker for marker in _CONDUCTOR_CLI_ONLY if marker in out]
    assert not leaked, f"conductor[{preset_name}] leaked {leaked}"
    assert "CH_CAPABILITY: HOW TO RUN THIS CHAIN (shell-less harness)" in out
    assert "STEP A — CONDUCT P_i INLINE" in out
    assert "STEP B — WAIT FOR P_i's CLOSEOUT, THEN ADVANCE" in out
    assert "ready_to_advance True" in out
    assert "COORDINATING FROM A" in out


def test_conductor_runtime_cli_render_keeps_its_terminal_instructions():
    out = _conductor_runtime_render(None)
    for marker in _CONDUCTOR_CLI_ONLY:
        assert marker in out, f"CLI conductor lost {marker!r}"
    assert "COORDINATING FROM A" not in out


def test_conductor_preset_wait_step_does_not_claim_a_free_running_sub_orchestrator():
    for preset_name in _PRESETS:
        out = _conductor_runtime_render(preset_name)
        assert "runs FREE (STEP A released it)" not in out, f"conductor[{preset_name}] kept the released claim"
        assert "P_i is driven the way STEP A set it up" in out
        assert "by you, inline, as its orchestrator" in out
        assert "your spawn IS the release" not in out, f"conductor[{preset_name}] kept the spawn-release intro"
        assert "You are the SOLE spawner" not in out
        assert "You drive every project yourself" in out
        assert "One project at a\ntime" in out or "One project at a time" in out
    cli = _conductor_runtime_render(None)
    assert "P_i's sub-orch runs FREE (STEP A released it)" in cli
    assert "You are the SOLE spawner" in cli
    assert "your spawn IS the release" in cli


_SOLO_CLI_ONLY = (
    "sleep-and-check",
    "I can sleep and re-check",
    "Then sleep for the specified interval",
    "wake_in_minutes=15",
    "sleep 1 ",
    "Start-Sleep",
    "wait_seconds=45",
    "TIMED SLEEP",
    "CH6",
)
_SOLO_WORKER_START = {
    "multi_terminal": (
        "The USER opens each agent's new session",
        "User opens a new session and starts the agent",
        "Copy agent prompts from the dashboard to start them.",
    ),
    "subagent": ("I will spawn each agent directly via",),
}
_SOLO_MODES = list(_SOLO_WORKER_START)


def _solo_runtime_render(mode: str, preset_name: str | None) -> str:
    preset = get_preset(preset_name) if preset_name else None
    job = SimpleNamespace(project_id="P", job_type="orchestrator", job_id="JOB", mission="", created_at=None)
    execution = SimpleNamespace(
        agent_id="E",
        agent_display_name="orchestrator",
        agent_name="orchestrator",
        spawned_by=None,
        status="working",
        started_at=None,
        project_phase=None,
    )
    project = SimpleNamespace(
        execution_mode=mode, implementation_launched_at=1, auto_checkin_enabled=False, auto_checkin_interval=10
    )
    return assemble_mission_context(
        mock.Mock(),
        job=job,
        execution=execution,
        project=project,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={"JOB": ""},
        current_team_state=None,
        tenant_key="T",
        integrations={},
        preset=preset,
        detected_harness="claude-code",
        checkin_cadence_minutes=10,
    ).full_protocol


@pytest.mark.parametrize("preset_name", _PRESETS)
@pytest.mark.parametrize("mode", _SOLO_MODES)
def test_solo_runtime_preset_render_carries_no_cli_only_order(mode, preset_name):
    out = _solo_runtime_render(mode, preset_name)
    leaked = [marker for marker in _SOLO_CLI_ONLY if marker in out]
    assert not leaked, f"solo {mode}[{preset_name}] leaked {leaked}"
    assert "COORDINATING FROM A" in out
    for line in _SOLO_WORKER_START[mode]:
        assert line in out, f"solo {mode}[{preset_name}] lost the worker-start instruction {line!r}"
    assert "### RESTING STATES (between coordination loops)" in out
    assert "**Blocked vs Idle vs Sleeping:**" in out


def test_solo_runtime_cli_render_keeps_its_wait_orders():
    multi_terminal = _solo_runtime_render("multi_terminal", None)
    for marker in _SOLO_CLI_ONLY:
        assert marker in multi_terminal, f"CLI solo multi_terminal lost {marker!r}"
    subagent = _solo_runtime_render("subagent", None)
    for marker in ("I can sleep and re-check", "Then sleep for the specified interval", "wake_in_minutes=15"):
        assert marker in subagent, f"CLI solo subagent lost {marker!r}"
    for mode, out in (("multi_terminal", multi_terminal), ("subagent", subagent)):
        assert "COORDINATING FROM A" not in out
        for line in _SOLO_WORKER_START[mode]:
            assert line in out, f"CLI solo {mode} lost {line!r}"


_REFERENCE_SLEEP_OFFER = ("If user wants auto-monitoring", "wake_in_minutes=15", "Sleep locally")


def _staging_refetch_render(cli_mode: bool, preset_name: str | None) -> dict:
    return _build_orchestrator_protocol(
        cli_mode=cli_mode,
        project_id="P",
        orchestrator_id="JOB",
        tenant_key="T",
        include_implementation_reference=True,
        tool="claude-code" if cli_mode else "multi_terminal",
        preset=get_preset(preset_name) if preset_name else None,
        detected_harness="claude-code",
    )


@pytest.mark.parametrize("preset_name", _PRESETS)
@pytest.mark.parametrize("cli_mode", [False, True])
def test_staging_refetch_preset_render_carries_no_sleep_order(cli_mode, preset_name):
    chapters = _staging_refetch_render(cli_mode, preset_name)
    assert "ch6_auto_checkin" not in chapters
    reference = chapters["ch5_reference"]
    leaked = [marker for marker in _REFERENCE_SLEEP_OFFER if marker in reference]
    assert not leaked, f"staging refetch cli_mode={cli_mode}[{preset_name}] leaked {leaked}"
    assert "4. After dispatching agents: set_agent_status" in reference
    assert "COORDINATION PATTERNS:" in reference


def test_staging_refetch_cli_render_keeps_its_sleep_orders():
    multi_terminal = _staging_refetch_render(False, None)
    assert "CH6: CHECK-IN PROTOCOL" in multi_terminal["ch6_auto_checkin"]
    assert "ch6_auto_checkin" not in _staging_refetch_render(True, None)
    for cli_mode in (False, True):
        reference = _staging_refetch_render(cli_mode, None)["ch5_reference"]
        for marker in _REFERENCE_SLEEP_OFFER:
            assert marker in reference, f"CLI staging refetch cli_mode={cli_mode} lost {marker!r}"


def _drop_anchor_cases() -> list[tuple[str, str, str]]:
    from giljo_mcp.services import protocol_builder
    from giljo_mcp.services.protocol_sections import agent_lifecycle, chapters_coordination

    cases = [
        (
            "loop directive aside",
            chapters_coordination._LOOP_MECHANISM_ASIDE,
            chapters_coordination._build_thread_loop_directive(),
        ),
        (
            "loop directive shell sleep step",
            chapters_coordination._LOOP_SHELL_SLEEP_STEP,
            chapters_coordination._build_thread_loop_directive(),
        ),
    ]
    for tool in ("multi_terminal", "claude-code", "codex"):
        banner = agent_lifecycle._build_forbidden_banner("multi_terminal", tool)
        cases.append((f"banner sleep order [{tool}]", agent_lifecycle._BANNER_SLEEP_ORDER, banner))
    for cli_mode in (False, True):
        reference = _staging_refetch_render(cli_mode, None)["ch5_reference"]
        cases.append(
            (f"reference sleep offer [cli_mode={cli_mode}]", protocol_builder._REFERENCE_SLEEP_OFFER, reference)
        )
    for mode in _SOLO_MODES:
        body = _generate_orchestrator_protocol("J", "T", "E", execution_mode=mode, tool=mode)
        cases.append((f"body offer start [{mode}]", agent_lifecycle._AUTO_CHECKIN_OFFER_START, body))
        cases.append((f"body status legend [{mode}]", agent_lifecycle._STATUS_LEGEND_ANCHOR, body))
    return cases


def test_every_text_a_preset_render_drops_is_found_exactly_once_without_a_preset():
    from giljo_mcp.services.protocol_sections import agent_lifecycle

    drifted = [
        f"{name}: found {text.count(anchor)}x" for name, anchor, text in _drop_anchor_cases() if text.count(anchor) != 1
    ]
    assert not drifted, f"drop anchors no longer match the source text: {drifted}"
    for mode in _SOLO_MODES:
        body = _generate_orchestrator_protocol("J", "T", "E", execution_mode=mode, tool=mode)
        assert body.index(agent_lifecycle._AUTO_CHECKIN_OFFER_START) < body.index(agent_lifecycle._STATUS_LEGEND_ANCHOR)


if __name__ == "__main__":  # pragma: no cover - fixture regeneration entry point
    import sys

    if "--write" in sys.argv:
        payload = json.dumps(_render_goldens(), indent=2, ensure_ascii=False)
        _FIXTURE.write_text(payload + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {len(_render_goldens())} golden cases to {_FIXTURE}")
    else:
        print("pass --write to (re)generate the golden fixture")
