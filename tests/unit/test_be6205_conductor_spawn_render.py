# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6207 (file-less one-liner) — conductor sub-orchestrator spawn renderer.

The chain conductor ALWAYS opens each project's sub-orchestrator in its OWN FRESH
OS terminal (every execution_mode); execution_mode governs only how the sub-orch
then spawns its WORKERS. BE-6207 renders ONE direct command per OS (a direct wt /
gnome-terminal / osascript call) — NO files written: ``$PWD`` self-resolves the cwd
and the tiny prompt rides inline (single-quoted). This supersedes BOTH the BE-6205
nested-quoted one-liner (an agent reformatted it -> 0x80070002) AND the interim
file-based launcher (it inherited stale files/ids and cluttered disk).

Pure-string assertions (no DB, no env, no subprocess) — parallel-safe under
pytest-xdist -n auto. Edition Scope: CE.
"""

from __future__ import annotations

import pytest

import giljo_mcp.prompts.launch_command_synth as lcs
from giljo_mcp.prompts.launch_command_synth import (
    AUTONOMY_FLAGS,
    autonomy_flag,
    build_conductor_thin_prompt,
    render_suborch_spawn_command,
)


_RUN = "RUN123"

# BE-9035c mode collapse: the sub-orch spawn renderer dispatches on the 2 topology
# MODES, not a per-CLI binary. Every non-multi_terminal token — the canonical
# ``subagent`` mode AND all 5 stored legacy tokens (``*_cli`` / ``generic_mcp``, which
# all fold to subagent) — renders the UNIVERSAL ``<your-harness>`` PLACEHOLDER block
# (no baked binary). ``multi_terminal`` alone LISTS one command per classic harness.
_SUBAGENT_MODES = (
    "subagent",
    "claude_code_cli",
    "codex_cli",
    "gemini_cli",
    "antigravity_cli",
    "generic_mcp",
)
_ALL_MODES = (*_SUBAGENT_MODES, "multi_terminal")

# The classic harness binaries multi_terminal lists (registry order) with their flags.
_CLASSIC_BINARIES = ("claude", "codex", "gemini", "agy")


# ---------------------------------------------------------------------------
# REGRESSION LOCK — the 0x80070002 failure classes must never reappear
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("mode", _ALL_MODES)
def test_no_start_process_no_files_no_nested_quoting(mode: str) -> None:
    """Three failure classes are regression-locked here:

    1. The BE-6205 nested one-liner `powershell.exe -Command "Start-Process wt
       -ArgumentList '<single string>'"` an agent reformatted into array form.
    2. ANY `Start-Process wt` form — the -ArgumentList ARRAY @(...) ALSO shattered the
       'giljo sub-orch' title (Start-Process joins array elements on spaces without
       re-quoting).
    3. The interim FILE-based launcher (write launch.ps1 + suborch.txt) — it inherited
       stale files/ids and cluttered disk.

    The renderer now emits ONE direct command per OS: no Start-Process, no launcher /
    prompt FILES, and no <YOUR_CWD> ($PWD self-resolves)."""
    out = render_suborch_spawn_command(mode, _RUN)
    assert "Start-Process" not in out, "BE-6207: invoke the terminal directly, never via Start-Process"
    assert 'powershell.exe -Command "Start-Process wt' not in out, "no powershell.exe -Command wrapper one-liner"
    assert "launch.ps1" not in out and "launch.sh" not in out, "file-less: no launcher FILE is written"
    assert "suborch.txt" not in out, "file-less: no prompt FILE is written"
    assert "<YOUR_CWD>" not in out, "$PWD self-resolves the cwd — no placeholder"
    assert "wt -w 0 new-tab" in out, "the Windows spawn is a direct wt invocation"


@pytest.mark.parametrize("mode", _ALL_MODES)
def test_no_tabcolor_noise(mode: str) -> None:
    """--tabColor is cosmetic and an extra arg to mis-quote — dropped on Windows."""
    out = render_suborch_spawn_command(mode, _RUN)
    assert "tabColor" not in out, "drop the Windows tab color (cosmetic noise)"


# ---------------------------------------------------------------------------
# The file-less mechanism — direct call + $PWD cwd + inline prompt
# ---------------------------------------------------------------------------


def test_windows_command_is_direct_wt_with_pwd_and_inline_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    # BE-9035c: the direct pwsh -NoExit / claude launch line now lives on the
    # multi_terminal (list-every-classic-harness) path.
    # TSK-9263: pin pwsh-present so the byte assertion is host-independent
    # (a no-PS7 Windows host would otherwise render the powershell fallback).
    monkeypatch.setattr(lcs, "_pwsh_available", lambda: True)
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "wt -w 0 new-tab --title 'giljo sub-orch' -d \"$PWD\"" in out, "direct wt, spaced title, $PWD cwd"
    assert "pwsh -NoExit -Command \"claude --dangerously-skip-permissions '" in out, "inline single-quoted prompt"


# ---------------------------------------------------------------------------
# TSK-9263 — Windows launch-shell ladder: pwsh (PS7) preferred, powershell
# (stock Windows PowerShell 5.1) as the runtime fallback. PS7 is NOT stock
# Windows, so a CE install on a plain Windows host must get a spawn command
# its box can actually run. Mirrors the Linux gnome-terminal ->
# x-terminal-emulator fallback ladder idiom already in this module.
# ---------------------------------------------------------------------------


def test_win_spawn_stays_pwsh_when_pwsh_present(monkeypatch: pytest.MonkeyPatch) -> None:
    """PS7 host: the validated pwsh -NoExit launch line is unchanged."""
    monkeypatch.setattr(lcs, "_is_windows_host", lambda: True)
    monkeypatch.setattr(lcs, "_pwsh_available", lambda: True)
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "pwsh -NoExit -Command" in out, "PS7 host keeps the preferred pwsh launch shell"
    assert "powershell -NoExit" not in out, "no fallback shell when pwsh exists"


def test_win_spawn_falls_back_to_powershell_when_pwsh_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    """No-PS7 Windows host: fall back to the stock powershell binary."""
    monkeypatch.setattr(lcs, "_is_windows_host", lambda: True)
    monkeypatch.setattr(lcs, "_pwsh_available", lambda: False)
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "powershell -NoExit -Command" in out, "stock Windows host must get a runnable shell"
    assert "pwsh -NoExit" not in out, "must not emit a binary the host does not have"


def test_win_spawn_keeps_pwsh_on_non_windows_host(monkeypatch: pytest.MonkeyPatch) -> None:
    """Non-Windows server host (SaaS / Linux CI): which('pwsh') says nothing about
    the REMOTE Windows reader's box — keep the validated pwsh default so the
    render (and its byte-pinned goldens) stays host-independent off-Windows."""
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
    """<P_i> and <SUB_ORCH_JOB_ID> ride INLINE in the command (the agent substitutes
    two UUIDs — no special chars, no file). True on BOTH dispatch paths."""
    for mode in ("multi_terminal", "subagent"):
        out = render_suborch_spawn_command(mode, _RUN)
        assert "<P_i>" in out
        assert "<SUB_ORCH_JOB_ID>" in out


# ---------------------------------------------------------------------------
# Autonomy flag single-sourcing (multi_terminal lists every classic harness w/ flag)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("binary", _CLASSIC_BINARIES)
def test_flag_is_single_sourced_from_autonomy_flags(binary: str) -> None:
    """BE-9035c: the per-harness autonomy flag now appears on the multi_terminal
    list-all path (one command per classic harness), single-sourced from AUTONOMY_FLAGS
    (derived from the HARNESSES table)."""
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert AUTONOMY_FLAGS[binary] in out, f"multi_terminal must carry {binary}'s flag {AUTONOMY_FLAGS[binary]}"


def test_multi_terminal_lists_every_classic_binary_not_only_claude() -> None:
    """The 'bakes its own binary' intent is now the multi_terminal list-all path:
    it must name codex / gemini / agy too, never collapse every harness to claude
    (the field bug where a non-claude conductor got a baked claude command)."""
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    for binary in _CLASSIC_BINARIES:
        assert binary in out, f"multi_terminal must list the {binary} command variant"


@pytest.mark.parametrize("mode", _SUBAGENT_MODES)
def test_subagent_render_bakes_no_binary_and_no_one_shot_flag(mode: str) -> None:
    """Every subagent-shaped mode renders the universal <your-harness> PLACEHOLDER: a
    stay-open, seeded ``cmd /k <harness> --prompt`` form. It bakes NO concrete binary
    (the collapse ended per-CLI baking) and never uses the -p one-shot launch flag that
    would run-and-exit the spawned tab."""
    out = render_suborch_spawn_command(mode, _RUN)
    assert "<your-harness>" in out, f"{mode}: must render the self-substitution placeholder"
    assert 'cmd /k <your-harness> --prompt "' in out, f"{mode}: stay-open seeded launch form"
    assert "--prompt" in out, f"{mode}: seeds the session (not a one-shot)"
    assert " -p " not in out, f"{mode}: must not use the -p one-shot launch flag"
    for baked in _CLASSIC_BINARIES:
        assert baked not in out, f"{mode}: must NOT bake a {baked} command (its harness is unknown here)"


@pytest.mark.parametrize("mode", _ALL_MODES)
def test_no_bare_p_one_shot_flag(mode: str) -> None:
    """NEVER the -p one-shot launch flag (runs once then EXITS — would kill the spawned
    tab). Holds on BOTH dispatch paths. (The subagent placeholder prose NAMES ``--print``
    only to warn AGAINST it; the launch line itself uses ``--prompt``.)"""
    out = render_suborch_spawn_command(mode, _RUN)
    assert " -p " not in out, f"{mode}: must not use the -p one-shot flag"


def test_multi_terminal_never_uses_print_flag() -> None:
    """The multi_terminal list-all path (real, baked launch lines) must never emit
    --print or -p — a one-shot form would kill the spawned tab."""
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "--print" not in out
    assert " -p " not in out


# ---------------------------------------------------------------------------
# BINARY RESOLUTION footgun (the load-bearing one) — post-collapse, a non-claude
# legacy chain must render the PLACEHOLDER, never silently bake a 'claude' command.
# ---------------------------------------------------------------------------


def test_codex_legacy_mode_bakes_no_claude_uses_placeholder() -> None:
    """A stored codex_cli chain folds to subagent → renders <your-harness>; it must NOT
    silently bake a 'claude' (or 'codex') command — the collapse ended per-CLI baking."""
    out = render_suborch_spawn_command("codex_cli", _RUN)
    assert "<your-harness>" in out, "codex_cli: must render the placeholder"
    assert "claude" not in out, "codex_cli: must NOT leak a bare claude command"
    assert "codex" not in out, "codex_cli: must NOT bake a codex command either"


def test_gemini_and_agy_legacy_modes_bake_no_claude_use_placeholder() -> None:
    for mode in ("gemini_cli", "antigravity_cli"):
        out = render_suborch_spawn_command(mode, _RUN)
        assert "<your-harness>" in out, f"{mode}: must render the placeholder"
        assert "claude" not in out, f"{mode}: must NOT leak a bare claude command"


# ---------------------------------------------------------------------------
# agy autonomy flag correction + interactive-seeded prompt form
# ---------------------------------------------------------------------------


def test_agy_uses_dangerously_skip_permissions_not_yolo() -> None:
    # BE-9035c: AUTONOMY_FLAGS is DERIVED from the HARNESSES table; agy's real
    # autonomy flag is --dangerously-skip-permissions, NEVER Gemini's --yolo.
    assert AUTONOMY_FLAGS["agy"] == "--dangerously-skip-permissions"
    assert autonomy_flag("agy") == "--dangerously-skip-permissions"
    assert AUTONOMY_FLAGS["agy"] != "--yolo", "agy must not derive the wrong --yolo flag"
    # On the multi_terminal list-all path, agy's line carries its correct flag.
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "agy --dangerously-skip-permissions" in out


def test_agy_seeds_interactive_prompt_flag() -> None:
    # The multi_terminal list-all path renders agy with its --prompt-interactive seed.
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert "--prompt-interactive" in out, "agy must seed via --prompt-interactive"


# ---------------------------------------------------------------------------
# Statelessness — pure function of (execution_mode, run_id)
# ---------------------------------------------------------------------------


def test_render_is_pure() -> None:
    a = render_suborch_spawn_command("claude_code_cli", _RUN)
    b = render_suborch_spawn_command("claude_code_cli", _RUN)
    assert a == b, "the renderer must be a pure function of its inputs"


def test_render_carries_run_id() -> None:
    out = render_suborch_spawn_command("claude_code_cli", _RUN)
    assert _RUN in out


# ---------------------------------------------------------------------------
# Per-OS coverage + validation labels
# ---------------------------------------------------------------------------


# BE-9035c: the per-OS blocks + [binary | VALIDATED/pending] validation taxonomy now
# live on the multi_terminal (list-every-classic-harness) path.


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


@pytest.mark.parametrize("binary", ["codex", "gemini", "agy"])
def test_non_claude_pending_validation(binary: str) -> None:
    """Only claude (on Windows/Linux) is VALIDATED; codex/gemini/agy have flags set but
    the invocation is not yet binary-verified — each is labelled pending validation."""
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    assert f"[{binary} | spawn syntax pending validation]" in out


# ---------------------------------------------------------------------------
# multi_terminal — every harness variant + elect-your-harness note
# ---------------------------------------------------------------------------


def test_multi_terminal_lists_all_harness_variants() -> None:
    out = render_suborch_spawn_command("multi_terminal", _RUN)
    for binary in ("claude", "codex", "gemini", "agy"):
        assert binary in out, f"multi_terminal must list the {binary} command variant"
    assert "elected" in out.lower(), "must tell the conductor to run the harness it elected"


def test_subagent_render_names_the_runtime_resolved_harness_placeholder() -> None:
    """BE-9035c: a subagent render no longer NAMES a baked harness (the driving CLI is
    resolved at RUNTIME, unknown at this session-less render point). It opens by saying
    so and carries the <your-harness> placeholder the conductor substitutes itself."""
    out = render_suborch_spawn_command("subagent", _RUN)
    assert out.startswith("Subagent mode: your driving harness is resolved at runtime")
    assert "<your-harness>" in out


# ---------------------------------------------------------------------------
# BE-9033 — generic_mcp conductor sub-orch spawn: <your-harness> placeholder,
# NEVER a baked claude with a VALIDATED tag (the field bug where an opencode
# conductor read [claude | VALIDATED] and spawned a CLAUDE terminal). generic_mcp
# has cli_binary=None, which used to collide with the multi_terminal sentinel and
# fall into the "list every CLI" branch.
# ---------------------------------------------------------------------------


def test_generic_mcp_uses_placeholder_not_a_baked_binary() -> None:
    """generic_mcp's harness is unknown to us — render <your-harness>, never a baked CLI."""
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert "<your-harness>" in out, "generic_mcp must render the self-substitution placeholder"
    for baked in ("claude", "codex", "gemini", "agy"):
        assert baked not in out, f"generic_mcp must NOT bake a {baked} command (its harness is unknown)"


def test_generic_mcp_never_carries_a_validated_tag() -> None:
    """The [claude | VALIDATED] tag is exactly what pulled a generic harness to claude in
    the field — we validated OUR CLIs, not the user's, so NOTHING here is 'VALIDATED'."""
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert "VALIDATED" not in out
    assert "[claude" not in out, "no per-harness claude launch line for generic_mcp"


def test_generic_mcp_windows_uses_cmd_k_not_pwsh_noexit() -> None:
    """Windows uses `cmd /k <your-harness>` (BE-9015 syntax) so a .cmd/.bat shim like
    opencode.cmd resolves from PATH — a pwsh -NoExit wrapper would not find it."""
    out = render_suborch_spawn_command("generic_mcp", _RUN)
    assert 'cmd /k <your-harness> --prompt "' in out, "Windows launch is `cmd /k <your-harness> --prompt`"
    # The ONLY mention of pwsh -NoExit is the guidance warning AGAINST it — never in a command line.
    assert "pwsh -NoExit -Command" not in out, "generic_mcp must not wrap the harness in pwsh -NoExit"


def test_generic_mcp_states_the_launch_contract_and_escape_hatch() -> None:
    """The contract (stay-open+seeded, unattended) replaces baked flags; the escape hatch
    routes a no-terminal harness to its subagent mechanism or inline conducting."""
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


# ---------------------------------------------------------------------------
# Thin prompt — must be safe INLINE (single-quoted on the command line)
# ---------------------------------------------------------------------------


def test_thin_prompt_is_inline_safe() -> None:
    """The prompt rides on the command line single-quoted, so it must contain no
    apostrophe (closes the quote), no ';' (wt tab delimiter), and no '"'."""
    prompt = build_conductor_thin_prompt(_RUN)
    assert "'" not in prompt, "inline single-quoted prompt must not contain an apostrophe"
    assert ";" not in prompt, "thin prompt must not contain ';' (wt splits tabs on it)"
    assert '"' not in prompt, "thin prompt must not contain a double-quote"
    assert _RUN in prompt
    assert "<SUB_ORCH_JOB_ID>" in prompt
    assert "get_job_mission" in prompt
    assert "health_check" in prompt


# ---------------------------------------------------------------------------
# BE-9291 (DoD step 5) — the spawn prompt must name the FK Hub-discovery path
#
# The retired convention discovered a chain hub by substring-searching its own
# SUBJECT for the run id. BE-9291 moved discovery onto ``comm_threads.sequence_run_id``
# and then removed the run id from new hub subjects — so ``search_threads`` with the
# run id as the query now returns NOTHING. The spawn prompt hands the sub-orch its run
# id in the same sentence, so naming a search tool without naming its argument is an
# invitation to search by the one identifier in scope. That is this project's own
# SILENT failure shape: no error, the sub-orch simply never finds its hub.
#
# The prompt must therefore name the CALL and what it RETURNS, not just a tool.
# ---------------------------------------------------------------------------


def test_thin_prompt_names_the_fk_hub_discovery_path() -> None:
    """The spawn prompt routes Hub discovery through the FK, not the retired subject
    search: it names the CALL (``get_context`` chain) and its RESULT (``hub_thread_id``),
    plus the read tool. Naming a tool without its argument is what let the sub-orch fall
    back to the run id, which no longer resolves."""
    prompt = build_conductor_thin_prompt(_RUN)
    assert "get_context chain" in prompt, "the discovery CALL must be named, not just its result"
    assert "hub_thread_id" in prompt, "the spawn prompt must name the FK discovery result"
    assert "get_thread_history" in prompt, "the sub-orch still needs the Hub READ tool"
    # NEGATIVE ON THE FORM, NOT THE BARE NAME — deliberate, and it is not a weaker
    # assertion by accident. ``search_threads`` is still a legitimate general-purpose
    # tool whose bare name appears in the CH_SUB_ORCHESTRATOR ToolSearch bootstrap hint.
    # This prompt is embedded VERBATIM into the CH_CHAIN_DRIVE render (once per platform
    # preset), so a bare-name negative copied from here to any render-level test would be
    # false for a reason with nothing to do with discovery. Pin the retired PAIR instead.
    assert "(search_threads," not in prompt, "the retired subject-search discovery pair must not return"


@pytest.mark.parametrize("mode", _ALL_MODES)
def test_spawn_command_ships_the_fk_hub_discovery_path(mode: str) -> None:
    """Every rendered spawn command — the thing a sub-orchestrator is actually launched
    with, on every mode — carries the FK discovery path and not the retired pair."""
    out = render_suborch_spawn_command(mode, _RUN)
    assert "get_context chain" in out
    assert "hub_thread_id" in out
    assert "(search_threads," not in out, "the retired subject-search discovery pair must not return"


# ---------------------------------------------------------------------------
# BE-9092 — elected-harness-row spawn render: the multi_terminal block narrows to
# the DETECTED harness's single command row (full OSxharness matrix as the fallback
# when detection is absent / generic / unknown / opencode). detected_harness=None
# (the default) MUST keep today's full-matrix render byte-for-byte.
# ---------------------------------------------------------------------------

# The detectable harness token -> the launcher binary its single row uses.
_DETECTED_HARNESS_TO_BINARY = {
    "claude-code": "claude",
    "codex": "codex",
    "gemini": "gemini",
    "antigravity": "agy",
}


def test_be9092_no_detection_is_byte_identical_to_full_matrix() -> None:
    """MANDATORY (no-detection): detected_harness=None — and the default (arg omitted) —
    render the FULL matrix, byte-for-byte identical to the pre-9092 render. This is the
    load-bearing byte-safety floor for the VALIDATED, test-pinned launch commands."""
    full = render_suborch_spawn_command("multi_terminal", _RUN)
    assert render_suborch_spawn_command("multi_terminal", _RUN, detected_harness=None) == full
    # The default (arg omitted) is the same no-detection path.
    assert render_suborch_spawn_command("multi_terminal", _RUN) == full
    # Full matrix still lists every classic harness command row.
    for binary in _CLASSIC_BINARIES:
        assert f"[{binary} |" in full, f"full matrix must list the {binary} command row"


@pytest.mark.parametrize("harness_token", ["generic", "opencode", "unknown-future-cli", ""])
def test_be9092_generic_unknown_opencode_fall_back_to_full_matrix(harness_token: str) -> None:
    """MANDATORY (unknown/generic client): a non-narrowing detection — ``generic`` (the
    fail-safe floor), ``opencode`` (a cmd-launched harness NOT in the pwsh matrix), an
    unregistered future token, or empty — renders the FULL matrix byte-for-byte. Only a
    concrete harness whose binary is one of the matrix rows narrows."""
    full = render_suborch_spawn_command("multi_terminal", _RUN)
    assert render_suborch_spawn_command("multi_terminal", _RUN, detected_harness=harness_token) == full


@pytest.mark.parametrize(("harness_token", "binary"), sorted(_DETECTED_HARNESS_TO_BINARY.items()))
def test_be9092_detected_harness_renders_exactly_one_row(harness_token: str, binary: str) -> None:
    """MANDATORY (detected-harness): a concrete detected harness narrows the block to
    EXACTLY its own command row — the detected binary's ``[binary | ...]`` label is
    present and every OTHER classic binary's command row is gone. All three OS blocks
    remain (the narrowing is per-harness, not per-OS)."""
    out = render_suborch_spawn_command("multi_terminal", _RUN, detected_harness=harness_token)
    assert f"[{binary} |" in out, f"{harness_token}: must render the {binary} command row"
    for other in _CLASSIC_BINARIES:
        if other != binary:
            assert f"[{other} |" not in out, f"{harness_token}: must NOT render the {other} command row"
    # Per-OS coverage is preserved — one row, still across all three OSes.
    assert "WINDOWS (wt tab)" in out
    assert "LINUX (gnome-terminal)" in out
    assert "macOS (Terminal.app)" in out
    # The narrowed intro names the detected binary and stays on the file-less direct path.
    assert f"detected as {binary}" in out
    assert "wt -w 0 new-tab" in out


def test_be9092_detected_row_is_selected_verbatim_from_the_full_matrix() -> None:
    """The narrowed row is a byte-for-byte SLICE of the full matrix, never a newly
    synthesized command — so the detected case cannot drift the VALIDATED launch lines.
    Every indented command line in the detected render appears verbatim in the full one."""
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
    """The whole point (payload win): narrowing to one row shrinks the block materially
    (approx -6KB of the conductor render when a harness is detected)."""
    full = render_suborch_spawn_command("multi_terminal", _RUN)
    detected = render_suborch_spawn_command("multi_terminal", _RUN, detected_harness="claude-code")
    assert len(detected) < len(full), "a single-row render must be smaller than the full matrix"


@pytest.mark.parametrize("mode", _SUBAGENT_MODES)
def test_be9092_subagent_mode_ignores_detected_harness(mode: str) -> None:
    """Detection only narrows the multi_terminal matrix. Every subagent-shaped mode
    renders the universal <your-harness> placeholder REGARDLESS of detected_harness —
    byte-identical with or without it (the placeholder already self-substitutes)."""
    baseline = render_suborch_spawn_command(mode, _RUN)
    assert render_suborch_spawn_command(mode, _RUN, detected_harness="claude-code") == baseline
    assert "<your-harness>" in baseline
