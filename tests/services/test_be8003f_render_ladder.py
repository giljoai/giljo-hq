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
from giljo_mcp.services.protocol_sections.agent_lifecycle import _generate_orchestrator_protocol
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol
from giljo_mcp.services.protocol_sections.chapters_chain import (
    _build_ch_capability,
    _build_ch_chain_drive,
    _build_chain_drive_step_a,
)
from giljo_mcp.services.protocol_sections.orchestrator_body import render_capability_ladder


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
        cases[f"s1_capability::{mode}"] = _build_ch_capability(mode, True)
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
    out = _build_ch_capability("multi_terminal", False, preset=preset)
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


if __name__ == "__main__":  # pragma: no cover - fixture regeneration entry point
    import sys

    if "--write" in sys.argv:
        payload = json.dumps(_render_goldens(), indent=2, ensure_ascii=False)
        _FIXTURE.write_text(payload + "\n", encoding="utf-8", newline="\n")
        print(f"wrote {len(_render_goldens())} golden cases to {_FIXTURE}")
    else:
        print("pass --write to (re)generate the golden fixture")
