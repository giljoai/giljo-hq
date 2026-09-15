# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import shutil
import sys
from typing import Any

from giljo_mcp.platform_registry import CLI_BINARIES, HARNESSES, MODE_MULTI_TERMINAL, get_harness


DEFAULT_CLI_TOOL = "claude"

SUPPORTED_OSES: tuple[str, ...] = ("windows", "linux", "macos")

AUTONOMY_FLAGS: dict[str, str] = {h.cli_binary: h.autonomy_flag for h in HARNESSES if h.autonomy_flag}

PROMPT_FLAGS: dict[str, str] = {h.cli_binary: h.launch_prompt_flag for h in HARNESSES if h.launch_prompt_flag}


def resolve_binary(cli_tool: str | None) -> str:
    return CLI_BINARIES.get((cli_tool or DEFAULT_CLI_TOOL), CLI_BINARIES[DEFAULT_CLI_TOOL])


def autonomy_flag(binary: str) -> str:
    return AUTONOMY_FLAGS.get(binary, "")


def prompt_flag(binary: str) -> str:
    return PROMPT_FLAGS.get(binary, "")


def build_loaded_prompt(job_id: str) -> str:
    jid = job_id or "<job_id>"
    return (
        "You are a GiljoAI agent. First verify the MCP connection with health_check, "
        f"then load your mission by calling get_job_mission(job_id={jid!r}) and execute "
        "the returned mission. Report progress with report_progress and call complete_job "
        "when done."
    )




def posix_single_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"


def pwsh_single_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def applescript_quote(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"')




def _binary_with_flag(binary: str) -> str:
    tokens = [binary, autonomy_flag(binary), prompt_flag(binary)]
    return " ".join(t for t in tokens if t) + " "


def windows_command(binary: str, title: str, seed_prompt: str) -> str:
    static_flags = [f for f in (autonomy_flag(binary), prompt_flag(binary)) if f]
    arg_list = ",".join([*static_flags, pwsh_single_quote(seed_prompt)])
    return f"Start-Process {binary} -ArgumentList {arg_list}"


def linux_command(binary: str, title: str, seed_prompt: str) -> str:
    return (
        f"gnome-terminal --title={posix_single_quote(title)} -- "
        f"{_binary_with_flag(binary)}{posix_single_quote(seed_prompt)}"
    )


def linux_command_fallback(binary: str, title: str, seed_prompt: str) -> str:
    return f"x-terminal-emulator -e {_binary_with_flag(binary)}{posix_single_quote(seed_prompt)}"


def macos_command(binary: str, title: str, seed_prompt: str) -> str:
    shell_cmd = f"{_binary_with_flag(binary)}{posix_single_quote(seed_prompt)}"
    script = f'tell application "Terminal" to do script "{applescript_quote(shell_cmd)}"'
    return "osascript -e " + posix_single_quote(script)


def synthesize_agent_launch(agent: dict[str, Any]) -> dict[str, Any]:
    cli_tool = agent.get("cli_tool") or DEFAULT_CLI_TOOL
    binary = resolve_binary(cli_tool)
    title = agent.get("agent") or "agent"
    seed = agent.get("seed_prompt") or ""
    return {
        "agent": title,
        "cli_tool": cli_tool,
        "job_id": agent.get("job_id", ""),
        "commands": {
            "windows": windows_command(binary, title, seed),
            "linux": linux_command(binary, title, seed),
            "linux_fallback": linux_command_fallback(binary, title, seed),
            "macos": macos_command(binary, title, seed),
        },
        "macos_validated": False,
    }


def synthesize_launch_commands(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [synthesize_agent_launch(agent) for agent in agents]





def _ordered_spawn_binaries() -> tuple[str, ...]:
    return tuple(h.cli_binary for h in HARNESSES if h.launch_shell == "pwsh")


def _detected_spawn_binary(detected_harness: str | None) -> str | None:
    harness = get_harness(detected_harness)
    if harness is not None and harness.cli_binary in _ordered_spawn_binaries():
        return harness.cli_binary
    return None


def build_conductor_thin_prompt(run_id: str) -> str:
    rid = run_id or "<run_id>"
    return (
        "You are the sub-orchestrator for project <P_i> in chain run "
        f"{rid}. Verify the MCP connection with health_check, then load your mission by "
        "calling get_job_mission with job_id <SUB_ORCH_JOB_ID> and execute it. Coordinate "
        "via get_context chain -> hub_thread_id and get_thread_history, not return values."
    )


def _harness_prefix(binary: str) -> str:
    parts = [binary, autonomy_flag(binary), prompt_flag(binary)]
    return " ".join(p for p in parts if p)


_WIN_SHELL_PRIMARY = "pwsh"
_WIN_SHELL_FALLBACK = "powershell"


def _is_windows_host() -> bool:
    return sys.platform == "win32"


def _pwsh_available() -> bool:
    return shutil.which(_WIN_SHELL_PRIMARY) is not None


def resolve_windows_launch_shell() -> str:
    if _is_windows_host() and not _pwsh_available():
        return _WIN_SHELL_FALLBACK
    return _WIN_SHELL_PRIMARY


_WIN_SPAWN = "wt -w 0 new-tab --title 'giljo sub-orch' -d \"$PWD\" {win_shell} -NoExit -Command \"{prefix} '{prompt}'\""
_LINUX_SPAWN = (
    "gnome-terminal --working-directory=\"$PWD\" --title='giljo sub-orch' -- bash -c \"{prefix} '{prompt}'; exec bash\""
)
_MACOS_SPAWN = (
    'osascript -e "tell application \\"Terminal\\" to do script \\"cd \\\\\\"$PWD\\\\\\" && {prefix} \'{prompt}\'\\""'
)


_GENERIC_HARNESS_TOKEN = "<your-harness>"

_GENERIC_WIN_SPAWN = 'wt -w 0 new-tab --title "giljo sub-orch" -d "$PWD" cmd /k {harness} --prompt "{prompt}"'
_GENERIC_LINUX_SPAWN = (
    'gnome-terminal --working-directory="$PWD" --title="giljo sub-orch" -- {harness} --prompt "{prompt}"'
)
_GENERIC_MACOS_SPAWN = (
    'osascript -e \'tell application "Terminal" to do script "cd \\"$PWD\\" && {harness} --prompt \\"{prompt}\\""\''
)


def _render_generic_mcp_suborch_spawn(prompt: str) -> str:
    win = _GENERIC_WIN_SPAWN.format(harness=_GENERIC_HARNESS_TOKEN, prompt=prompt)
    linux = _GENERIC_LINUX_SPAWN.format(harness=_GENERIC_HARNESS_TOKEN, prompt=prompt)
    macos = _GENERIC_MACOS_SPAWN.format(harness=_GENERIC_HARNESS_TOKEN, prompt=prompt)
    return (
        "Subagent mode: your driving harness is resolved at runtime (not declared), so the\n"
        "per-OS commands below carry a <your-harness> placeholder. Replace it with the SAME\n"
        "CLI running you right now (you know your own binary), and replace --prompt with your\n"
        "CLI's own prompt-seeding flag (opencode uses --prompt; many CLIs take the prompt\n"
        'positionally, e.g. `<your-harness> "<prompt>"`). Your substituted command MUST:\n'
        "  1. STAY OPEN, seeded — an interactive session with the prompt pre-loaded. NEVER a\n"
        "     one-shot / print / run-and-exit form (-p / --print / a bare `run`) — the tab\n"
        "     would execute once and DIE.\n"
        "  2. RUN UNATTENDED — add your harness's auto-approve / skip-permissions flag, or the\n"
        "     spawned session stalls on its first tool call waiting for a human.\n"
        "  3. Substitute <P_i> and <SUB_ORCH_JOB_ID> in the prompt; change NOTHING else.\n"
        "CANNOT open OS terminals (a chat / web / IDE session)? Do NOT run these — spawn the\n"
        "sub-orchestrator via your harness's own subagent / agent / delegate mechanism, or (if\n"
        "you have none) conduct the chain's projects INLINE, one after another, yourself.\n\n"
        "── WINDOWS (Windows Terminal) ──\n"
        f"  {win}\n"
        "  Key: the cmd /k wrapper (NOT pwsh -NoExit) so a .cmd/.bat shim like opencode.cmd resolves from PATH.\n\n"
        "── LINUX (gnome-terminal) ──\n"
        f"  {linux}\n"
        "  (konsole / xterm work too — use the emulator your desktop has installed.)\n\n"
        "── macOS (Terminal.app) — pending validation ──\n"
        f"  {macos}"
    )


class _OsCmdSpec:

    __slots__ = ("label", "template", "validated")

    def __init__(self, label: str, template: str, *, validated: bool) -> None:
        self.label = label
        self.template = template
        self.validated = validated


_OS_SPAWN: dict[str, _OsCmdSpec] = {
    "windows": _OsCmdSpec("WINDOWS (wt tab)", _WIN_SPAWN, validated=True),
    "linux": _OsCmdSpec("LINUX (gnome-terminal)", _LINUX_SPAWN, validated=True),
    "macos": _OsCmdSpec("macOS (Terminal.app)", _MACOS_SPAWN, validated=False),
}

SPAWN_OSES: tuple[str, ...] = tuple(_OS_SPAWN.keys())


def _validation_label(binary: str, os_name: str) -> str:
    if binary == "claude" and _OS_SPAWN[os_name].validated:
        return "VALIDATED"
    return "spawn syntax pending validation"


def _harness_command(template: str, binary: str, os_name: str, prompt: str) -> str:
    cmd = template.format(
        prefix=_harness_prefix(binary),
        prompt=prompt,
        win_shell=resolve_windows_launch_shell(),
    )
    return f"  [{binary} | {_validation_label(binary, os_name)}]\n  {cmd}"


def _os_command_block(os_name: str, binary: str | None, prompt: str) -> str:
    spec = _OS_SPAWN[os_name]
    if binary is not None:
        body = _harness_command(spec.template, binary, os_name, prompt)
    else:
        body = "\n".join(_harness_command(spec.template, b, os_name, prompt) for b in _ordered_spawn_binaries())
    return (
        f"── {spec.label} ──\n"
        "  RUN this ONE command (substitute <P_i> and <SUB_ORCH_JOB_ID> in the prompt; "
        "change NOTHING else):\n"
        f"{body}"
    )


def render_suborch_spawn_command(execution_mode: str | None, run_id: str, detected_harness: str | None = None) -> str:
    mode_raw = (execution_mode or MODE_MULTI_TERMINAL).strip() or MODE_MULTI_TERMINAL
    prompt = build_conductor_thin_prompt(run_id)

    if mode_raw != MODE_MULTI_TERMINAL:
        return _render_generic_mcp_suborch_spawn(prompt)

    binary = _detected_spawn_binary(detected_harness)
    if binary is not None:
        harness_line = (
            f"Mode {mode_raw}: your session's harness was detected as {binary} — only its "
            "spawn command is shown below (the full harness matrix is emitted only when no "
            "harness is detected)."
        )
    else:
        harness_line = (
            f"Mode {mode_raw}: each OS block lists one command per harness "
            "(claude / codex) — run the one for the harness you elected."
        )
    blocks = "\n\n".join(_os_command_block(os_name, binary, prompt) for os_name in SPAWN_OSES)
    return (
        f"{harness_line}\n"
        "For YOUR OS (a local fact), run the ONE command below — no files to write, "
        "substitute only the two UUIDs into the prompt. macOS is rendered but pending "
        "validation.\n\n"
        f"{blocks}"
    )



INHERIT = "inherit"
_HINT_FOOTNOTE = (
    "(Hints are prose for the harness; 'inherit' means the same as the orchestrator. "
    "Ignore a hint your harness cannot honour.)\n"
)


def normalize_hint(value: str | None) -> str:
    text = (value or "").strip()
    return text or INHERIT


def render_harness_launch_block(cli_tool: str | None, *, model: str | None, effort: str | None) -> str:
    harness = next((h for h in HARNESSES if h.cli_tool == (cli_tool or "")), None)
    lines = ["## HARNESS\n"]
    if harness is None:
        lines.append(
            "Harness: Generic. Launch this agent in any MCP-capable harness connected to this server\n"
            "and seed it with this prompt.\n"
        )
    else:
        binary = harness.cli_binary
        parts = [binary]
        if harness.autonomy_flag:
            parts.append(harness.autonomy_flag)
        if harness.launch_prompt_flag:
            parts.append(harness.launch_prompt_flag)
        parts.append('"<this prompt>"')
        lines.append(
            f"Harness: {harness.display_label}. Launch this agent in a fresh {harness.display_label} session:\n"
            f"  {' '.join(parts)}\n"
        )
    model_hint = normalize_hint(model)
    effort_hint = normalize_hint(effort)
    hints = []
    if model_hint != INHERIT:
        hints.append(f"Model hint: {model_hint}\n")
    if effort_hint != INHERIT:
        hints.append(f"Effort hint: {effort_hint}\n")
    if hints:
        lines.extend(hints)
        lines.append(_HINT_FOOTNOTE)
    return "".join(lines)
