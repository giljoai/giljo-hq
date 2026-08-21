# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""INF-6049c: per-agent terminal launch-command synthesis (LOCAL launcher).

Multi-terminal launch opens one terminal per spawned agent, each running that
agent's assigned coding CLI pre-seeded with its initiation prompt. The FastAPI
server may be REMOTE (SaaS) and cannot open windows on the user's desktop, so
this module produces a STRUCTURED, ADVISORY ``launch_commands`` array that the
DRIVING AGENT (the local Claude session) — or the user — executes locally. No
server-side process spawning: these are strings, never run here.

SAFETY (load-bearing): a seed prompt can contain quotes, semicolons, ``$``,
backticks, spaces and newlines. Every per-OS synthesizer wraps the seed (and the
window title) in that shell's strongest literal-quoting form so a hostile prompt
can NEITHER break out of the argument NOR inject an extra command:

- POSIX (Linux / macOS shell layer): single-quote wrap; the only metacharacter
  inside single quotes is ``'`` itself, closed-escaped-reopened as ``'\\''``.
- PowerShell (Windows): single-quote wrap; the only escape is a doubled ``''``.
- AppleScript string layer (macOS, best-effort): backslash + double-quote escape,
  then the whole ``osascript -e`` argument is POSIX single-quoted.

macOS is BEST-EFFORT and explicitly **not validated** — macOS validation is
pending; each entry carries ``macos_validated=False`` so callers can surface that.
"""

from __future__ import annotations

import shutil
import sys
from typing import Any

# Coding-tool identifier (the agent_templates.cli_tool vocabulary) -> the CLI
# binary that launches it. Single source: PlatformRegistry (re-exported here so
# existing importers keep resolving the name). BE-3010a.
# BE-9035c: the mode collapse removed the per-CLI PLATFORMS rows; the conductor
# sub-orchestrator spawn renderer now dispatches on the 2 MODES (multi_terminal ->
# list every classic harness variant; subagent -> the universal <your-harness>
# placeholder, since the harness is runtime-resolved and unknown at this
# session-less render point). The per-harness launch facts come from HARNESSES.
from giljo_mcp.platform_registry import CLI_BINARIES, HARNESSES, MODE_MULTI_TERMINAL, get_harness


DEFAULT_CLI_TOOL = "claude"

# The operating systems we synthesize for. macOS is best-effort / not validated.
SUPPORTED_OSES: tuple[str, ...] = ("windows", "linux", "macos")

# BE-6182: per-harness AUTONOMY flag — without it the launched terminal stalls on
# the harness's first permission prompt (the tester's launched terminal booted, hit
# get_job_mission, then stalled because no autonomy flag was emitted). The agent runs
# unattended in its own terminal, so it MUST skip approval prompts. Keyed by launcher
# BINARY (the cli_tool→binary map collapses antigravity→agy). Values match the
# documented per-CLI autonomy flags; an unknown binary gets no flag (safe default — a
# non-runnable-but-inert command beats inventing a flag).
# BE-6205: agy's real autonomy flag (verified via `agy --help`) is
# --dangerously-skip-permissions ("Auto-approve all tool permission requests without
# prompting"), NOT Gemini's --yolo (a wrong derivation inference — agy shares Gemini's
# @-syntax for agent SPAWN, not its autonomy flag).
# BE-9035c: single source is the HARNESSES table (each harness row carries its
# autonomy_flag). Keyed by launcher BINARY (the cli_tool->binary map collapses
# antigravity->agy); a harness with no autonomy flag (opencode) is omitted, so an
# unknown binary gets "" from autonomy_flag() — a non-runnable-but-inert command
# beats inventing a flag.
AUTONOMY_FLAGS: dict[str, str] = {h.cli_binary: h.autonomy_flag for h in HARNESSES if h.autonomy_flag}


def resolve_binary(cli_tool: str | None) -> str:
    """Map a coding-tool identifier to its launcher binary, defaulting to claude.

    Unknown / empty values fall back to the default tool's binary rather than
    raising — the mapping is advisory and an unset template cli_tool means
    "claude" (the documented default).
    """
    return CLI_BINARIES.get((cli_tool or DEFAULT_CLI_TOOL), CLI_BINARIES[DEFAULT_CLI_TOOL])


def autonomy_flag(binary: str) -> str:
    """Return the unattended-autonomy flag for ``binary`` ("" if unknown).

    BE-6182: a per-agent terminal runs unattended, so it must bypass the harness's
    interactive approval prompts or it stalls on first tool call.
    """
    return AUTONOMY_FLAGS.get(binary, "")


def build_loaded_prompt(job_id: str) -> str:
    """Natural-language boot prompt for a launched agent terminal (BE-6182).

    The prior synth passed RAW tool-call seed lines as the terminal argument
    (``mcp__giljo_mcp__health_check()\\nmcp__giljo_mcp__get_job_mission(...)``),
    which a CLI does not interpret as instructions. Emit a natural-language prompt
    that tells the agent to verify MCP, LOAD its mission via get_job_mission, and
    execute it — the loaded-prompt form a coding CLI actually acts on.
    """
    jid = job_id or "<job_id>"
    return (
        "You are a GiljoAI agent. First verify the MCP connection with health_check, "
        f"then load your mission by calling get_job_mission(job_id={jid!r}) and execute "
        "the returned mission. Report progress with report_progress and call complete_job "
        "when done."
    )


# ---------------------------------------------------------------------------
# Per-shell literal quoting (the security-critical core)
# ---------------------------------------------------------------------------


def posix_single_quote(value: str) -> str:
    """Wrap ``value`` so a POSIX shell treats it as one literal argument.

    Inside single quotes every character is literal except ``'``; that is closed,
    backslash-escaped, and reopened (``'\\''``). Bulletproof against ``"``, ``;``,
    ``$``, backticks, spaces, and newlines.
    """
    return "'" + value.replace("'", "'\\''") + "'"


def pwsh_single_quote(value: str) -> str:
    """Wrap ``value`` as a PowerShell single-quoted (literal) string.

    PowerShell single-quoted strings expand nothing; the only escape is a doubled
    ``''`` for an embedded single quote. ``$``, backtick, ``;`` and ``"`` are all
    inert inside it.
    """
    return "'" + value.replace("'", "''") + "'"


def applescript_quote(value: str) -> str:
    """Escape ``value`` for embedding inside an AppleScript double-quoted string."""
    return value.replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# Per-OS command synthesis
# ---------------------------------------------------------------------------


def _binary_with_flag(binary: str) -> str:
    """``binary`` followed by its autonomy flag (or bare binary if none). BE-6182.

    Preserves the leading ``{binary} `` token the per-OS synthesizers emit (so the
    binary is still the first executable word) while inserting the unattended-autonomy
    flag immediately after it.
    """
    flag = autonomy_flag(binary)
    return f"{binary} {flag} " if flag else f"{binary} "


def windows_command(binary: str, title: str, seed_prompt: str) -> str:
    """PowerShell ``Start-Process`` opening a NEW console running ``binary`` seeded.

    BE-6182: the autonomy flag and the natural-language loaded prompt are passed as
    ``-ArgumentList`` so the spawned terminal runs unattended instead of stalling on
    a permission prompt. Each element of ``-ArgumentList`` is its own argument; the
    seed is PowerShell single-quoted so quotes/semicolons/``$`` in the prompt cannot
    break the call or spawn a second command. The autonomy flag is a static token
    (no user input) so it is emitted unquoted, before the quoted seed.
    ``Start-Process`` (vs ``wt new-tab``) is deliberate: ``wt`` parses ``;`` as a tab
    delimiter — a footgun for seeds that contain it.
    """
    flag = autonomy_flag(binary)
    arg_list = f"{flag},{pwsh_single_quote(seed_prompt)}" if flag else pwsh_single_quote(seed_prompt)
    return f"Start-Process {binary} -ArgumentList {arg_list}"


def linux_command(binary: str, title: str, seed_prompt: str) -> str:
    """gnome-terminal opening a new window running ``binary`` seeded (BE-6182: with
    autonomy flag + natural-language loaded prompt).

    Falls back to ``x-terminal-emulator`` on hosts without gnome-terminal (the
    caller surfaces both). Title and seed are POSIX single-quoted; the autonomy flag
    is a static token (no user input) so it needs no quoting.
    """
    return (
        f"gnome-terminal --title={posix_single_quote(title)} -- "
        f"{_binary_with_flag(binary)}{posix_single_quote(seed_prompt)}"
    )


def linux_command_fallback(binary: str, title: str, seed_prompt: str) -> str:
    """x-terminal-emulator fallback for hosts without gnome-terminal (BE-6182)."""
    return f"x-terminal-emulator -e {_binary_with_flag(binary)}{posix_single_quote(seed_prompt)}"


def macos_command(binary: str, title: str, seed_prompt: str) -> str:
    """Best-effort osascript launcher (macOS validation pending).

    BE-6182: carries the autonomy flag + natural-language loaded prompt. Three
    quoting layers, innermost-out: the shell command POSIX-single-quotes the seed;
    that command is AppleScript-string-escaped; the whole ``osascript -e`` script is
    POSIX single-quoted for the outer shell.
    """
    shell_cmd = f"{_binary_with_flag(binary)}{posix_single_quote(seed_prompt)}"
    script = f'tell application "Terminal" to do script "{applescript_quote(shell_cmd)}"'
    return "osascript -e " + posix_single_quote(script)


def synthesize_agent_launch(agent: dict[str, Any]) -> dict[str, Any]:
    """Synthesize the per-OS launch commands for ONE agent spec.

    Args:
        agent: ``{"agent": display_name, "cli_tool": str, "job_id": str,
                  "seed_prompt": str}``. Missing/empty ``cli_tool`` defaults to
                  claude.

    Returns:
        ``{"agent", "cli_tool", "job_id", "commands": {windows, linux,
        linux_fallback, macos}, "macos_validated": False}``.
    """
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
        # macOS osascript path is best-effort; surfaced so callers can warn.
        "macos_validated": False,
    }


def synthesize_launch_commands(agents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Synthesize ``launch_commands`` for a list of agent specs (advisory payload).

    One entry per agent. Empty input -> empty list (e.g. a staging-phase payload
    with no team spawned yet), which keeps the field present but harmless.
    """
    return [synthesize_agent_launch(agent) for agent in agents]


# ===========================================================================
# BE-6207: CONDUCTOR sub-orchestrator spawn — file-LESS one-line renderer
# ===========================================================================
#
# The chain conductor ALWAYS opens each project's sub-orchestrator in its OWN FRESH
# OS terminal (every execution_mode); execution_mode governs only how the sub-orch
# then spawns its WORKERS. This is DISTINCT from the per-WORKER advisory path above
# (windows_command/linux_command/...): those seed a WORKER terminal from a free-form
# job seed; the functions below render what the conductor RUNS at CH_CHAIN_DRIVE
# STEP A to open a SUB-ORCHESTRATOR.
#
# DESIGN HISTORY (why this is now ONE line, no files):
#   1. BE-6205 emitted a four-level nested-quoted one-liner
#      (powershell -Command "Start-Process wt -ArgumentList '...cmd /k claude \"<p>\"'").
#      An agent reformatted it -> 0x80070002. Root cause = LATITUDE.
#   2. A first BE-6207 cut moved the dangerous quoting into a SERVER-AUTHORED launcher
#      FILE (write launch.ps1 + suborch.txt, then run one line). But (a) we had ALSO
#      switched to a direct ``wt`` call — flat, not fragile — so the file sealed
#      nothing that still needed sealing; and (b) the file introduced its OWN failures:
#      a stale launch.ps1 / stale ids from a prior run were inherited, plus disk
#      clutter and a write/cleanup lifecycle. Pure downside.
#   3. NOW: NO files. The conductor runs ONE direct command per OS. The dangerous
#      nesting is gone (direct ``wt``); ``$PWD`` self-resolves the cwd (no path
#      placeholder); and the prompt is TINY and disposable — it only tells the
#      sub-orch to call get_job_mission (which fetches the real 50KB mission AFTER
#      boot), so it rides inline, single-quoted, free of ``;`` / ``"`` / ``'``. The
#      ONLY agent substitution is two UUIDs (<P_i>, <SUB_ORCH_JOB_ID>) — no special
#      chars. VERIFIED end-to-end on Windows 11 (direct wt -> fresh pwsh tab ->
#      inline multi-word prompt survives). No stale-file class can exist.

# Binaries that seed an INTERACTIVE session via a prompt flag instead of a trailing
# positional. agy takes --prompt-interactive (verified via `agy --help`); claude /
# codex / gemini accept the seed positionally. NEVER -p/--print — that runs the
# harness ONCE and EXITS, killing the spawned tab.
_INTERACTIVE_PROMPT_FLAG: dict[str, str] = {"agy": "--prompt-interactive"}


def _ordered_spawn_binaries() -> tuple[str, ...]:
    """Classic-CLI launcher binaries in registry order (claude, codex, gemini, agy).

    BE-9035c: sourced from HARNESSES, restricted to the ``pwsh``-launched classic CLIs
    so the multi_terminal spawn block (which renders every variant with the
    ``pwsh -NoExit`` template) stays byte-identical. opencode (``cmd /k`` launch shell)
    is deliberately excluded from this pwsh-templated list.
    """
    return tuple(h.cli_binary for h in HARNESSES if h.launch_shell == "pwsh")


def _detected_spawn_binary(detected_harness: str | None) -> str | None:
    """The single spawn binary the multi_terminal block narrows to, or None (BE-9092).

    The multi_terminal spawn block normally LISTS one command per classic harness
    (claude / codex / gemini / agy) because the harness is a human-elected local fact
    unknown at this session-less render point. When the session's harness WAS detected
    from clientInfo (BE-9035b, stamped on ``resolved_harness``), narrow to just that
    harness's row.

    DETECTION-driven and conservative: narrowing fires ONLY for a concrete harness whose
    launcher binary is one of the ``pwsh``-templated classic rows the full matrix already
    lists — so the single row is byte-identical to that row in the full matrix, never a
    newly synthesized (and therefore un-validated) command. Absent / ``generic`` / unknown
    detection, and opencode (a ``cmd``-launched harness NOT in the pwsh matrix), all return
    None → the caller keeps today's full OSxharness matrix, byte-for-byte.
    """
    harness = get_harness(detected_harness)
    if harness is not None and harness.cli_binary in _ordered_spawn_binaries():
        return harness.cli_binary
    return None


def build_conductor_thin_prompt(run_id: str) -> str:
    """The thin sub-orchestrator boot prompt — rendered INLINE in the spawn command.

    Server-rendered with ``run_id``; ``<P_i>`` and ``<SUB_ORCH_JOB_ID>`` stay as
    placeholders the conductor substitutes per project. It rides on the command line
    SINGLE-QUOTED, so it MUST stay free of ``'`` (apostrophe — would close the quote),
    ``;`` (the ``wt`` tab delimiter), and ``"``. The substitutions are UUIDs (no special
    chars). Kept tiny on purpose: it only tells the sub-orch to call get_job_mission,
    which fetches the real mission AFTER boot — so the inline prompt never needs to grow.
    """
    rid = run_id or "<run_id>"
    return (
        "You are the sub-orchestrator for project <P_i> in chain run "
        f"{rid}. Verify the MCP connection with health_check, then load your mission by "
        "calling get_job_mission with job_id <SUB_ORCH_JOB_ID> and execute it. Coordinate "
        "via get_context chain -> hub_thread_id and get_thread_history, not return values."
    )


def _harness_prefix(binary: str) -> str:
    """``<binary> <autonomy-flag> [<interactive-flag>]`` — the leading run tokens.

    The single-quoted prompt is appended after this by the OS template. agy seeds
    interactively via --prompt-interactive; the others take the prompt positionally.
    NEVER -p/--print (runs once then EXITS — kills the spawned tab).
    """
    parts = [binary]
    flag = autonomy_flag(binary)
    if flag:
        parts.append(flag)
    interactive = _INTERACTIVE_PROMPT_FLAG.get(binary)
    if interactive:
        parts.append(interactive)
    return " ".join(parts)


# Per-OS ONE-LINE spawn command. ``{prefix}`` = server-resolved "<binary> <flags>";
# ``{prompt}`` = the inline thin prompt (single-quoted). cwd self-resolves via the
# shell's own ``$PWD`` — no path placeholder, no file. The agent substitutes only the
# two UUIDs inside the prompt and runs the line. Windows is e2e-verified; the title is
# intentionally hyphenless-free of the tabColor (dropped: cosmetic, and a spaced/extra
# arg is just more to mis-quote).
# TSK-9263: the Windows launch-shell LADDER — pwsh (PS7) preferred, powershell
# (stock Windows PowerShell 5.1) as the fallback. PS7 is NOT stock Windows, so a
# CE install on a plain Windows host must get a spawn line its box can run. Same
# idiom as the Linux gnome-terminal -> x-terminal-emulator ladder above: prefer
# the primary, degrade to what exists. Resolution is HOST-gated: only a Windows
# host without pwsh degrades (CE runs the server on the user's own box, so the
# probe is truthful there); a non-Windows server host (SaaS / CI) cannot probe
# the REMOTE Windows reader's box and keeps the validated pwsh default — which
# also keeps the byte-pinned render goldens host-independent off-Windows.
_WIN_SHELL_PRIMARY = "pwsh"
_WIN_SHELL_FALLBACK = "powershell"


def _is_windows_host() -> bool:
    return sys.platform == "win32"


def _pwsh_available() -> bool:
    return shutil.which(_WIN_SHELL_PRIMARY) is not None


def resolve_windows_launch_shell() -> str:
    """The shell binary the Windows spawn line uses: ``pwsh``, unless synthesizing
    ON a Windows host where pwsh is absent — then stock ``powershell`` (TSK-9263).
    Both accept the identical ``-NoExit -Command`` form the template emits."""
    if _is_windows_host() and not _pwsh_available():
        return _WIN_SHELL_FALLBACK
    return _WIN_SHELL_PRIMARY


_WIN_SPAWN = "wt -w 0 new-tab --title 'giljo sub-orch' -d \"$PWD\" {win_shell} -NoExit -Command \"{prefix} '{prompt}'\""
_LINUX_SPAWN = (
    "gnome-terminal --working-directory=\"$PWD\" --title='giljo sub-orch' -- bash -c \"{prefix} '{prompt}'; exec bash\""
)
# macOS — rendered but not validated (validation pending). osascript driving Terminal.app.
_MACOS_SPAWN = (
    'osascript -e "tell application \\"Terminal\\" to do script \\"cd \\\\\\"$PWD\\\\\\" && {prefix} \'{prompt}\'\\""'
)


# ===========================================================================
# BE-9033: generic_mcp CONDUCTOR sub-orch spawn — <your-harness> placeholder path
# ===========================================================================
#
# generic_mcp's Platform row has cli_binary=None (its harness is UNKNOWN to us: any
# MCP-connected client that is not one of our 4 registered CLIs). That None collides
# with the multi_terminal sentinel below, so BEFORE this branch a generic_mcp conductor
# fell into the "list every CLI" path and got claude tagged [claude | VALIDATED] — the
# exact field bug where an opencode conductor spawned a CLAUDE terminal for its sub-orch.
#
# Fix: render a <your-harness> PLACEHOLDER the conductor substitutes with its own CLI,
# NEVER a baked binary and NEVER a "VALIDATED" tag (we validated OUR CLIs, not the
# user's). Windows uses ``cmd /k`` (NOT ``pwsh -NoExit``) so a .cmd/.bat shim like
# opencode.cmd resolves from PATH — the SAME syntax BE-9015 gave the WORKER CH3 spawn,
# so both paths tell an opencode user the identical launch form. The prompt is
# double-quoted (cmd treats single quotes as literal chars): build_conductor_thin_prompt
# guarantees the prompt is free of ``"`` / ``;`` / ``'``, so double-quoting is safe.
_GENERIC_HARNESS_TOKEN = "<your-harness>"

_GENERIC_WIN_SPAWN = 'wt -w 0 new-tab --title "giljo sub-orch" -d "$PWD" cmd /k {harness} --prompt "{prompt}"'
_GENERIC_LINUX_SPAWN = (
    'gnome-terminal --working-directory="$PWD" --title="giljo sub-orch" -- {harness} --prompt "{prompt}"'
)
# macOS — rendered but not validated (validation pending). osascript driving Terminal.app.
_GENERIC_MACOS_SPAWN = (
    'osascript -e \'tell application "Terminal" to do script "cd \\"$PWD\\" && {harness} --prompt \\"{prompt}\\""\''
)


def _render_generic_mcp_suborch_spawn(prompt: str) -> str:
    """Render the generic_mcp conductor sub-orch spawn block (BE-9033).

    generic_mcp's harness is UNKNOWN to us (no registered cli_binary), so this MUST NOT
    reuse the CLI multi-harness renderer (which lists our 4 CLIs and tags claude
    VALIDATED — the field path that made an opencode conductor spawn a claude terminal).
    Instead render a ``<your-harness>`` placeholder the conductor substitutes with its
    own CLI, plus the launch CONTRACT (stay-open+seeded, unattended, UUIDs only) and the
    no-terminal escape hatch (harness subagent mechanism / inline conducting). Windows
    uses ``cmd /k`` (not ``pwsh -NoExit``) so a .cmd shim resolves from PATH — the same
    form BE-9015 gave the WORKER CH3 path, so both tell an opencode user the identical
    launch line.
    """
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
    """Per-OS one-line spawn command template + validation flag."""

    __slots__ = ("label", "template", "validated")

    def __init__(self, label: str, template: str, *, validated: bool) -> None:
        self.label = label
        self.template = template
        # ``validated`` = claude on this OS is binary-verified. macOS is never validated.
        self.validated = validated


# OS tokens in display order. Windows + Linux are validated for claude; macOS pending.
_OS_SPAWN: dict[str, _OsCmdSpec] = {
    "windows": _OsCmdSpec("WINDOWS (wt tab)", _WIN_SPAWN, validated=True),
    "linux": _OsCmdSpec("LINUX (gnome-terminal)", _LINUX_SPAWN, validated=True),
    "macos": _OsCmdSpec("macOS (Terminal.app)", _MACOS_SPAWN, validated=False),
}

SPAWN_OSES: tuple[str, ...] = tuple(_OS_SPAWN.keys())


def _validation_label(binary: str, os_name: str) -> str:
    """VALIDATED only for claude on Windows/Linux; everything else pending validation.

    The claude positional invocation is binary-verified on Windows AND Linux.
    codex/gemini/agy flags are set but the full invocation is not yet binary-verified,
    and macOS (osascript) validation is pending — all "pending validation".
    """
    if binary == "claude" and _OS_SPAWN[os_name].validated:
        return "VALIDATED"
    return "spawn syntax pending validation"


def _harness_command(template: str, binary: str, os_name: str, prompt: str) -> str:
    """One harness's spawn command line, labelled with its validation state.

    ``win_shell`` (TSK-9263) only appears in the Windows template; the extra
    kwarg is ignored by the Linux/macOS templates."""
    cmd = template.format(
        prefix=_harness_prefix(binary),
        prompt=prompt,
        win_shell=resolve_windows_launch_shell(),
    )
    return f"  [{binary} | {_validation_label(binary, os_name)}]\n  {cmd}"


def _os_command_block(os_name: str, binary: str | None, prompt: str) -> str:
    """Render the one-line spawn command(s) for one OS.

    For a resolved single ``binary`` one command is rendered; for ``multi_terminal``
    (``binary is None``) one command per harness is listed and the conductor runs the
    one for its elected harness.
    """
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
    """Render the file-LESS one-line sub-orchestrator spawn command(s) for STEP A.

    One block per OS (Windows / Linux / macOS). Each block is a SINGLE direct command
    the conductor runs to open a fresh terminal: a direct ``wt`` / ``gnome-terminal`` /
    ``osascript`` invocation, with cwd self-resolved via ``$PWD`` and the thin prompt
    inline (single-quoted). No files are written, so no stale-file class can exist.

    BE-9035c mode collapse — dispatch on the 2 topology MODES, not a per-CLI binary:

    - ``multi_terminal``: the harness is a human-elected local fact, so by default LIST
      one command per classic harness (claude / codex / gemini / agy) and the conductor
      runs the one it uses. BE-9092: when ``detected_harness`` names a concrete harness
      resolved from the session's clientInfo (BE-9035b), narrow to ONLY that harness's
      row — the single largest remaining chunk of the conductor render (approx -6KB). Detection
      absent / ``generic`` / unknown / opencode → the full matrix, BYTE-IDENTICAL to the
      pre-9092 render (``detected_harness=None`` is the default, so every unpatched caller
      and the no-detection golden are unchanged).
    - ``subagent`` (and every stored legacy ``*_cli`` / ``generic_mcp`` token, which all
      fold to subagent): the driving harness is RESOLVED AT RUNTIME from clientInfo and
      is UNKNOWN at this session-less render point, so render the universal
      ``<your-harness>`` placeholder the conductor substitutes with its own CLI (the
      BE-9033 renderer, generalized to the whole subagent mode). ``detected_harness`` is
      ignored here — the placeholder path already tells the conductor to substitute its
      own runtime-resolved harness.
    """
    mode_raw = (execution_mode or MODE_MULTI_TERMINAL).strip() or MODE_MULTI_TERMINAL
    prompt = build_conductor_thin_prompt(run_id)

    if mode_raw != MODE_MULTI_TERMINAL:
        # subagent + any legacy CLI/generic token → universal <your-harness> placeholder.
        return _render_generic_mcp_suborch_spawn(prompt)

    # multi_terminal → normally one command per classic harness; when the session's harness
    # was DETECTED (BE-9092) narrow to that ONE harness's row. binary=None (detection
    # absent / generic / unknown / opencode) keeps today's full matrix byte-for-byte.
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
            "(claude / codex / gemini / agy) — run the one for the harness you elected."
        )
    blocks = "\n\n".join(_os_command_block(os_name, binary, prompt) for os_name in SPAWN_OSES)
    return (
        f"{harness_line}\n"
        "For YOUR OS (a local fact), run the ONE command below — no files to write, "
        "substitute only the two UUIDs into the prompt. macOS is rendered but pending "
        "validation.\n\n"
        f"{blocks}"
    )
