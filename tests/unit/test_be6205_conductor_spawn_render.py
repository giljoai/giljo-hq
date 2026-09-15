# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

import giljo_mcp.prompts.launch_command_synth as lcs
from giljo_mcp.prompts.launch_command_synth import (
    AUTONOMY_FLAGS,
    build_conductor_thin_prompt,
    render_suborch_spawn_command,
)


_RUN = "RUN123"

_SUBAGENT_MODES = (
    "subagent",
    "claude_code_cli",
    "codex_cli",
    "gemini_cli",
    "antigravity_cli",
    "generic_mcp",
)
_ALL_MODES = (*_SUBAGENT_MODES, "multi_terminal")

_CLASSIC_BINARIES = ("claude", "codex")




@pytest.mark.parametrize("mode", _ALL_MODES)
def test_no_start_process_no_files_no_nested_quoting(mode: str) -> None:
    out = render_suborch_spawn_command(mode, _RUN)
    assert "Start-Process" not in out, "BE-6207: invoke the terminal directly, never via Start-Process"
    assert 'powershell.exe -Command "Start-Process wt' not in out, "no powershell.exe -Command wrapper one-liner"
    assert "launch.ps1" not in out and "launch.sh" not in out, "file-less: no launcher FILE is written"
    assert "suborch.txt" not in out, "file-less: no prompt FILE is written"
    assert "<YOUR_CWD>" not in out, "$PWD self-resolves the cwd — no placeholder"
    assert "wt -w 0 new-tab" in out, "the Windows spawn is a direct wt invocation"


@pytest.mark.parametrize("mode", _ALL_MODES)
def test_no_tabcolor_noise(mode: str) -> None:
    out = render_suborch_spawn_command(mode, _RUN)
    assert "tabColor" not in out, "drop the Windows tab color (cosmetic noise)"




def test_windows_command_is_direct_wt_with_pwd_and_inline_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lcs, "_pwsh_available", lambda: True)
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "wt -w 0 new-tab --title 'giljo sub-orch' -d \"$PWD\"" in out, "direct wt, spaced title, $PWD cwd"
    assert "pwsh -NoExit -Command \"claude --dangerously-skip-permissions '" in out, "inline single-quoted prompt"




def test_win_spawn_stays_pwsh_when_pwsh_present(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lcs, "_is_windows_host", lambda: True)
    monkeypatch.setattr(lcs, "_pwsh_available", lambda: True)
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "pwsh -NoExit -Command" in out, "PS7 host keeps the preferred pwsh launch shell"
    assert "powershell -NoExit" not in out, "no fallback shell when pwsh exists"


def test_win_spawn_falls_back_to_powershell_when_pwsh_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lcs, "_is_windows_host", lambda: True)
    monkeypatch.setattr(lcs, "_pwsh_available", lambda: False)
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "powershell -NoExit -Command" in out, "stock Windows host must get a runnable shell"
    assert "pwsh -NoExit" not in out, "must not emit a binary the host does not have"


def test_win_spawn_keeps_pwsh_on_non_windows_host(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lcs, "_is_windows_host", lambda: False)
    monkeypatch.setattr(lcs, "_pwsh_available", lambda: False)
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "pwsh -NoExit -Command" in out, "non-Windows host keeps the validated default"
    assert "powershell -NoExit" not in out


def test_linux_command_is_direct_gnome_terminal_with_pwd() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "gnome-terminal --working-directory=\"$PWD\" --title='giljo sub-orch'" in out
    assert "bash -c \"claude --dangerously-skip-permissions '" in out, "inline single-quoted prompt"
    assert "exec bash" in out, "keep the Linux tab open"


def test_inline_prompt_carries_substitutable_uuid_placeholders() -> None:
    for mode in ("multi_terminal", "subagent"):
        out = render_suborch_spawn_command(mode, _RUN)
        assert "<P_i>" in out
        assert "<SUB_ORCH_JOB_ID>" in out




@pytest.mark.parametrize("binary", _CLASSIC_BINARIES)
def test_flag_is_single_sourced_from_autonomy_flags(binary: str) -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert AUTONOMY_FLAGS[binary] in out, f"multi_terminal must carry {binary}'s flag {AUTONOMY_FLAGS[binary]}"


def test_multi_terminal_lists_every_classic_binary_not_only_claude() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    for binary in _CLASSIC_BINARIES:
        assert binary in out, f"multi_terminal must list the {binary} command variant"


@pytest.mark.parametrize("mode", _SUBAGENT_MODES)
def test_subagent_render_bakes_no_binary_and_no_one_shot_flag(mode: str) -> None:
    out = render_suborch_spawn_command(mode, _RUN)
    assert "<your-harness>" in out, f"{mode}: must render the self-substitution placeholder"
    assert 'cmd /k <your-harness> --prompt "' in out, f"{mode}: stay-open seeded launch form"
    assert "--prompt" in out, f"{mode}: seeds the session (not a one-shot)"
    assert " -p " not in out, f"{mode}: must not use the -p one-shot launch flag"
    for baked in _CLASSIC_BINARIES:
        assert baked not in out, f"{mode}: must NOT bake a {baked} command (its harness is unknown here)"


@pytest.mark.parametrize("mode", _ALL_MODES)
def test_no_bare_p_one_shot_flag(mode: str) -> None:
    out = render_suborch_spawn_command(mode, _RUN)
    assert " -p " not in out, f"{mode}: must not use the -p one-shot flag"


def test_multi_terminal_never_uses_print_flag() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "--print" not in out
    assert " -p " not in out




def test_codex_legacy_mode_bakes_no_claude_uses_placeholder() -> None:
    out = render_suborch_spawn_command("codex_cli", _RUN)
    assert "<your-harness>" in out, "codex_cli: must render the placeholder"
    assert "claude" not in out, "codex_cli: must NOT leak a bare claude command"
    assert "codex" not in out, "codex_cli: must NOT bake a codex command either"


def test_gemini_and_agy_legacy_modes_bake_no_claude_use_placeholder() -> None:
    for mode in ("gemini_cli", "antigravity_cli"):
        out = render_suborch_spawn_command(mode, _RUN)
        assert "<your-harness>" in out, f"{mode}: must render the placeholder"
        assert "claude" not in out, f"{mode}: must NOT leak a bare claude command"




def test_render_is_pure() -> None:
    a = render_suborch_spawn_command("claude_code_cli", _RUN)
    b = render_suborch_spawn_command("claude_code_cli", _RUN)
    assert a == b, "the renderer must be a pure function of its inputs"


def test_render_carries_run_id() -> None:
    out = render_suborch_spawn_command("claude_code_cli", _RUN)
    assert _RUN in out






def test_all_three_os_blocks_present() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "WINDOWS (wt tab)" in out
    assert "LINUX (gnome-terminal)" in out
    assert "macOS (Terminal.app)" in out


def test_claude_windows_and_linux_validated() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "claude --dangerously-skip-permissions" in out
    assert "[claude | VALIDATED]" in out, "claude on Windows/Linux is validated"


def test_macos_pending_validation() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "osascript" in out, "macOS uses osascript driving Terminal.app"
    assert "pending validation" in out, "macOS spawn is not binary-verified"


@pytest.mark.parametrize("binary", ["codex"])
def test_non_claude_pending_validation(binary: str) -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert f"[{binary} | spawn syntax pending validation]" in out




def test_multi_terminal_lists_all_harness_variants() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    for binary in ("claude", "codex"):
        assert binary in out, f"multi_terminal must list the {binary} command variant"
    assert "elected" in out.lower(), "must tell the conductor to run the harness it elected"


def test_subagent_render_names_the_runtime_resolved_harness_placeholder() -> None:
    out = render_suborch_spawn_command("subagent", _RUN)
    assert out.startswith("Subagent mode: your driving harness is resolved at runtime")
    assert "<your-harness>" in out




def test_generic_mcp_uses_placeholder_not_a_baked_binary() -> None:
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert "<your-harness>" in out, "generic_mcp must render the self-substitution placeholder"
    for baked in ("claude", "codex"):
        assert baked not in out, f"generic_mcp must NOT bake a {baked} command (its harness is unknown)"


def test_generic_mcp_never_carries_a_validated_tag() -> None:
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert "VALIDATED" not in out
    assert "[claude" not in out, "no per-harness claude launch line for generic_mcp"


def test_generic_mcp_windows_uses_cmd_k_not_pwsh_noexit() -> None:
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert 'cmd /k <your-harness> --prompt "' in out, "Windows launch is `cmd /k <your-harness> --prompt`"
    assert "pwsh -NoExit -Command" not in out, "generic_mcp must not wrap the harness in pwsh -NoExit"


def test_generic_mcp_states_the_launch_contract_and_escape_hatch() -> None:
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert "STAY OPEN" in out, "must require an interactive, seeded, stay-open session"
    assert "UNATTENDED" in out, "must require an unattended / auto-approve flag"
    assert "subagent" in out.lower(), "no-terminal harness → use its subagent/agent/delegate mechanism"
    assert "INLINE" in out, "or conduct the chain's projects inline in order"


def test_generic_mcp_carries_uuid_placeholders_and_all_three_os_blocks() -> None:
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert "<P_i>" in out and "<SUB_ORCH_JOB_ID>" in out, "the two substitutable UUIDs ride inline"
    assert "WINDOWS (Windows Terminal)" in out
    assert "LINUX (gnome-terminal)" in out
    assert "macOS (Terminal.app)" in out


def test_generic_mcp_render_is_pure_and_carries_run_id() -> None:
    a = render_suborch_spawn_command("generic_mcp", _RUN)
    b = render_suborch_spawn_command("generic_mcp", _RUN)
    assert a == b, "the generic_mcp render must be a pure function of its inputs"
    assert _RUN in a, "the run_id rides inline in the thin prompt"




def test_thin_prompt_is_inline_safe() -> None:
    prompt = build_conductor_thin_prompt(_RUN)
    assert "'" not in prompt, "inline single-quoted prompt must not contain an apostrophe"
    assert ";" not in prompt, "thin prompt must not contain ';' (wt splits tabs on it)"
    assert '"' not in prompt, "thin prompt must not contain a double-quote"
    assert _RUN in prompt
    assert "<SUB_ORCH_JOB_ID>" in prompt
    assert "get_job_mission" in prompt
    assert "health_check" in prompt




def test_thin_prompt_names_the_fk_hub_discovery_path() -> None:
    prompt = build_conductor_thin_prompt(_RUN)
    assert "get_context chain" in prompt, "the discovery CALL must be named, not just its result"
    assert "hub_thread_id" in prompt, "the spawn prompt must name the FK discovery result"
    assert "get_thread_history" in prompt, "the sub-orch still needs the Hub READ tool"
    assert "(list_threads," not in prompt, "the retired subject-search discovery pair must not return"


@pytest.mark.parametrize("mode", _ALL_MODES)
def test_spawn_command_ships_the_fk_hub_discovery_path(mode: str) -> None:
    out = render_suborch_spawn_command(mode, _RUN)
    assert "get_context chain" in out
    assert "hub_thread_id" in out
    assert "(list_threads," not in out, "the retired subject-search discovery pair must not return"



_DETECTED_HARNESS_TO_BINARY = {
    "claude-code": "claude",
    "codex": "codex",
}


def test_be9092_no_detection_is_byte_identical_to_full_matrix() -> None:
    full = render_suborch_spawn_command("multi_terminal", _RUN)
    assert render_suborch_spawn_command("multi_terminal", _RUN, detected_harness=None) == full
    assert render_suborch_spawn_command("multi_terminal", _RUN) == full
    for binary in _CLASSIC_BINARIES:
        assert f"[{binary} |" in full, f"full matrix must list the {binary} command row"


@pytest.mark.parametrize("harness_token", ["generic", "opencode", "unknown-future-cli", ""])
def test_be9092_generic_unknown_opencode_fall_back_to_full_matrix(harness_token: str) -> None:
    full = render_suborch_spawn_command("multi_terminal", _RUN)
    assert render_suborch_spawn_command("multi_terminal", _RUN, detected_harness=harness_token) == full


@pytest.mark.parametrize(("harness_token", "binary"), sorted(_DETECTED_HARNESS_TO_BINARY.items()))
def test_be9092_detected_harness_renders_exactly_one_row(harness_token: str, binary: str) -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN, detected_harness=harness_token)
    assert f"[{binary} |" in out, f"{harness_token}: must render the {binary} command row"
    for other in _CLASSIC_BINARIES:
        if other != binary:
            assert f"[{other} |" not in out, f"{harness_token}: must NOT render the {other} command row"
    assert "WINDOWS (wt tab)" in out
    assert "LINUX (gnome-terminal)" in out
    assert "macOS (Terminal.app)" in out
    assert f"detected as {binary}" in out
    assert "wt -w 0 new-tab" in out


def test_be9092_detected_row_is_selected_verbatim_from_the_full_matrix() -> None:
    full = render_suborch_spawn_command("multi_terminal", _RUN)
    detected = render_suborch_spawn_command("multi_terminal", _RUN, detected_harness="claude-code")
    command_lines = [
        ln
        for ln in detected.splitlines()
        if ln.startswith("  ") and any(tok in ln for tok in ("wt -w 0", "gnome-terminal", "osascript", "[claude |"))
    ]
    assert command_lines, "the detected render must contain the claude command rows"
    for ln in command_lines:
        assert ln in full, f"detected row line must be a verbatim slice of the full matrix: {ln!r}"


def test_be9092_detected_render_is_smaller_than_full_matrix() -> None:
    full = render_suborch_spawn_command("multi_terminal", _RUN)
    detected = render_suborch_spawn_command("multi_terminal", _RUN, detected_harness="claude-code")
    assert len(detected) < len(full), "a single-row render must be smaller than the full matrix"


@pytest.mark.parametrize("mode", _SUBAGENT_MODES)
def test_be9092_subagent_mode_ignores_detected_harness(mode: str) -> None:
    baseline = render_suborch_spawn_command(mode, _RUN)
    assert render_suborch_spawn_command(mode, _RUN, detected_harness="claude-code") == baseline
    assert "<your-harness>" in baseline
