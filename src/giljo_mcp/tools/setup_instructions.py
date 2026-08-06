# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Platform-specific setup instruction generator.

Sprint 002e: Extracted from tool_accessor.py (module-level function).
Zero coupling to ToolAccessor -- generates install instructions for
bootstrap_setup based on the target CLI platform.

TSK-6154: dispatch on the PlatformRegistry export-platform constants (BE-6117)
rather than bare string literals, so the export-vocabulary lives in one place.
"""

from giljo_mcp import branding
from giljo_mcp.platform_registry import (
    EXPORT_ANTIGRAVITY_CLI,
    EXPORT_CLAUDE_CODE,
    EXPORT_GEMINI_CLI,
    EXPORT_GENERIC,
)


# BE-9067: the canonical "what Giljo HQ is" primer, persisted into the agent's
# durable startup context (CLAUDE.md/AGENTS.md/GEMINI.md or a code-memory system)
# during first-time setup, so a fresh session already knows the platform mental
# model instead of re-deriving it or calling get_giljo_guide from cold every time.
# Defined ONCE here and referenced by every build_setup_instructions branch plus
# the giljo_setup inline branch -- never copy-paste per platform, that drifts.
# Kept well under 2KB on purpose: this is a persisted artifact, not the full guide.
GILJOAI_MCP_PRIMER = f"""\
## {branding.PRODUCT_NAME} -- what it is
A project-management and agent-coordination platform driven over MCP.
- Product -- top-level container holding baseline context (tech stack,
  architecture, conventions). Work happens under an active product.
- Project -- an actionable, multi-step body of work under a product. Agents
  execute it by receiving work-order assignments from an orchestrator.
- Orchestrator workflow -- the user activates a project; the orchestrator
  plans it, assigns jobs/work orders, and STOPS at staging (the human gate).
  The user triggers implementation; agents execute; the project closes out
  with a 360 memory entry.
- Chain execution -- the user links multiple projects to run back-to-back.
  The orchestrator is promoted to a conductor (master orchestrator) that
  spawns sub-orchestrators; each does its own staging, work-order writing,
  and team assembly for its project in the chain. A chain is multi-project,
  single-user (not Teams).
- Tasks -- a deferral list of smaller items the user can review and promote
  into projects.
- 360 memory -- the durable, detailed history layer; works alongside Git as
  the cross-session record.
- Commands -- the /giljo skill (or $giljo, or calling get_giljo_guide) loads
  the full command/routing instructions on demand.
"""


# Shared closing note for every platform branch. Defined ONCE (this file's
# never-copy-paste-per-platform rule) so the 410 recovery hint stays in sync.
# BE-9208: a stale link returns HTTP 410 — tell the agent the recovery path so
# the self-describing fix (re-run giljo_setup) reaches whoever hits the 410.
_DOWNLOAD_LINK_NOTE = (
    "Note: Download link expires in 15 minutes. If the download returns HTTP 410 "
    "(Gone), the link is stale — your agent templates changed after it was created; "
    "re-run giljo_setup for a fresh link."
)


def _primer_persist_step(home_dir: str, config_filename: str) -> str:
    """Ask-once consent + managed-block persist step, shared by every platform branch.

    Mirrors the existing GILJOAI_CODEX_SUBAGENT_DISPLAY marker pattern below: a
    dedicated marker pair so re-running giljo_setup replaces the block in place
    instead of appending a duplicate.
    """
    return (
        "Step P — Persist the GiljoAI primer into your durable startup context:\n"
        f'Ask the user ONCE: "May I add a short {branding.PRODUCT_NAME} primer to your '
        f"{home_dir}/{config_filename} so future sessions already understand the "
        'platform without re-fetching it?" If approved: back up an existing '
        f"{home_dir}/{config_filename} with a timestamped copy, then add or replace "
        "ONLY the block between the markers below (create the file if it does not "
        "exist). Write UTF-8 without BOM. Re-running giljo_setup replaces this block "
        "in place -- never append a duplicate copy.\n"
        "<!-- GILJOAI_MCP_PRIMER_START -->\n"
        f"{GILJOAI_MCP_PRIMER}"
        "<!-- GILJOAI_MCP_PRIMER_END -->\n"
        "If you also have a code-memory system (e.g. Serena's write_memory, or a "
        "native memory tool), save the same primer there too so it surfaces on "
        "recall. If you have neither a startup context file nor a memory system, "
        "suggest the user install a code-memory layer such as Serena (only if it "
        "can persist notes like this) and otherwise keep the primer in-context for "
        "this session.\n\n"
    )


def _primer_persist_step_generic() -> str:
    """Same persist step, worded for an unidentified platform (no known home dir)."""
    return (
        "Step P — Persist the GiljoAI primer into your durable startup context:\n"
        "Ask the user ONCE before editing any startup/context file your client "
        "reads on boot (e.g. CLAUDE.md, AGENTS.md, GEMINI.md, or your MCP client's "
        "equivalent). If approved: back up the file if it exists, then add or "
        "replace ONLY the block between the markers below (create the file if it "
        "does not exist). Write UTF-8 without BOM. Re-running giljo_setup replaces "
        "this block in place -- never append a duplicate copy.\n"
        "<!-- GILJOAI_MCP_PRIMER_START -->\n"
        f"{GILJOAI_MCP_PRIMER}"
        "<!-- GILJOAI_MCP_PRIMER_END -->\n"
        "If you also have a code-memory system (e.g. Serena's write_memory, or a "
        "native memory tool), save the same primer there too so it surfaces on "
        "recall. If you have neither a startup context file nor a memory system, "
        "suggest the user install a code-memory layer such as Serena (only if it "
        "can persist notes like this) and otherwise keep the primer in-context for "
        "this session.\n\n"
    )


def build_inline_primer_note() -> str:
    """Primer guidance for sessions with no home dir to write into (BE-9067).

    Used by giljo_setup's inline branch (web_sandbox / chat harnesses): no
    filesystem to persist into, so route to a code-memory system if one exists,
    else keep the primer in-context for the session. No OS-write instructions.
    """
    return (
        f"{branding.PRODUCT_NAME} primer for your own context (this session has no startup "
        "file to write):\n"
        f"{GILJOAI_MCP_PRIMER}"
        "If you have a code-memory system (e.g. Serena's write_memory, or a "
        "native memory tool), save this primer there so it surfaces on recall in "
        "future sessions. Otherwise, keep it in context for this session."
    )


def build_setup_instructions(platform: str, download_url: str) -> str:
    """Build a natural-language prompt the LLM will execute to install GiljoAI CLI integration."""
    if platform == EXPORT_CLAUDE_CODE:
        return (
            "Install the GiljoAI CLI integration. This is a one-time setup.\n\n"
            "Step 1 — Download:\n"
            f"Download: {download_url}\n"
            "Save the zip to a temp location (do NOT extract the whole zip to ~/.claude/ yet).\n\n"
            "Step 2 — Choose install scope:\n"
            "Ask the user ONCE via AskUserQuestion:\n"
            '  "What should giljo_setup install or refresh?"\n'
            "  Options: [Both commands/skills and agents, Commands/skills only, Agents only]\n"
            "Default to Both for first-time setup. Set INSTALL_COMMANDS=true for Both or "
            "Commands/skills only. Set INSTALL_AGENTS=true for Both or Agents only.\n\n"
            "Step 3 — Install commands if INSTALL_COMMANDS=true:\n"
            "Extract only the commands/ entries from the zip into ~/.claude/commands/ "
            "(create if needed, overwrite existing). If INSTALL_COMMANDS=false, do not touch "
            "~/.claude/commands/.\n\n"
            "Step 4 — Install agents if INSTALL_AGENTS=true (consent required if any exist):\n"
            "Check if ~/.claude/agents/ contains any .md files.\n"
            "  - If none exist (or the directory is missing): extract agents/* into "
            "~/.claude/agents/ and continue.\n"
            "  - If .md files already exist: ask the user ONCE via AskUserQuestion:\n"
            '      "GiljoAI agent templates already exist in ~/.claude/agents/. '
            "Overwrite with agent templates from the server? Any local edits will be lost. "
            'To preserve them, choose Skip agents (or re-run giljo_setup later with the Agents only scope)."\n'
            "      Options: [Overwrite, Skip agents]\n"
            "    - Overwrite -> extract agents/* into ~/.claude/agents/ (overwrite).\n"
            "    - Skip agents -> do NOT extract agents/*. Tell the user their existing "
            "agent files were preserved.\n"
            "If INSTALL_AGENTS=false, do not touch ~/.claude/agents/.\n\n"
            "Step 5 — Clean up:\n"
            "Delete the downloaded zip.\n\n"
            "Adapt all commands for the OS you are running on.\n\n"
            "Step 6 — Tell the user:\n"
            "Report exactly which scope was installed. If INSTALL_AGENTS=true, agent templates "
            "were installed to ~/.claude/agents/ with model: opus by default.\n"
            "If INSTALL_COMMANDS=true, this command is now available:\n"
            "- /giljo — create, read, and update projects and tasks (it loads the GiljoAI guide, then acts)\n\n"
            "Restart Claude Code after installing commands or agents.\n\n"
            f"{_primer_persist_step('~/.claude', 'CLAUDE.md')}"
            f"{_DOWNLOAD_LINK_NOTE}"
        )
    if platform == EXPORT_GEMINI_CLI:
        return (
            "Install the GiljoAI CLI integration. This is a one-time setup.\n\n"
            "Step 1 — Download:\n"
            f"Download: {download_url}\n"
            "Save the zip to a temp location (do NOT extract the whole zip to ~/.gemini/ yet).\n\n"
            "Step 1a — Choose install scope:\n"
            "Ask the user ONCE:\n"
            '  "What should giljo_setup install or refresh?"\n'
            "  Options: [Both commands/skills and agents, Commands/skills only, Agents only]\n"
            "Default to Both for first-time setup. Set INSTALL_COMMANDS=true for Both or "
            "Commands/skills only. Set INSTALL_AGENTS=true for Both or Agents only.\n\n"
            "Step 1b — Install commands if INSTALL_COMMANDS=true:\n"
            "Extract only the commands/ entries from the zip into ~/.gemini/commands/ "
            "(create if needed, overwrite existing). If INSTALL_COMMANDS=false, do not touch "
            "~/.gemini/commands/.\n\n"
            "Step 1c — Install agents if INSTALL_AGENTS=true (consent required if any exist):\n"
            "Check if ~/.gemini/agents/ contains any .md files.\n"
            "  - If none exist (or the directory is missing): extract agents/* into "
            "~/.gemini/agents/ and continue.\n"
            "  - If .md files already exist: ask the user ONCE:\n"
            '      "GiljoAI agent templates already exist in ~/.gemini/agents/. '
            "Overwrite with agent templates from the server? Any local edits will be lost. "
            'To preserve them, choose Skip agents (or re-run giljo_setup later with the Agents only scope)."\n'
            "      Options: [Overwrite, Skip agents]\n"
            "    - Overwrite -> extract agents/* into ~/.gemini/agents/ (overwrite).\n"
            "    - Skip agents -> do NOT extract agents/*. Tell the user their existing "
            "agent files were preserved.\n"
            "If INSTALL_AGENTS=false, do not touch ~/.gemini/agents/.\n\n"
            "Step 1d — Clean up:\n"
            "Delete the downloaded zip.\n\n"
            "Step 2 — Enable custom agents if INSTALL_AGENTS=true:\n"
            'Merge {"experimental": {"enableAgents": true}} into ~/.gemini/settings.json '
            "(create if it does not exist). Preserve all existing settings. If INSTALL_AGENTS=false, "
            "do not touch ~/.gemini/settings.json for this setup.\n"
            "IMPORTANT — Use a shell command for this step. Your file-write tool may be "
            "sandboxed to the workspace and unable to write to the home directory.\n"
            'Linux/macOS: python3 -c "'
            "import json,pathlib; "
            "p=pathlib.Path.home()/'.gemini'/'settings.json'; "
            "d=json.loads(p.read_text()) if p.exists() else {}; "
            "d.setdefault('experimental',{})['enableAgents']=True; "
            'p.write_text(json.dumps(d,indent=2))"\n'
            'Windows PowerShell: $p="$env:USERPROFILE\\.gemini\\settings.json"; '
            "$d=if(Test-Path $p){Get-Content $p -Raw|ConvertFrom-Json -AsHashtable}else{@{}}; "
            "if(-not $d.ContainsKey('experimental')){$d['experimental']=@{}}; "
            "$d['experimental']['enableAgents']=$true; "
            "$utf8NoBom=New-Object System.Text.UTF8Encoding($false); "
            "[System.IO.File]::WriteAllText($p,($d|ConvertTo-Json -Depth 10),$utf8NoBom)\n\n"
            "Adapt all commands for the OS you are running on.\n\n"
            "Step 3 — Tell the user:\n"
            "Report exactly which scope was installed. If INSTALL_AGENTS=true, agent templates "
            "were installed to ~/.gemini/agents/ with model: gemini-3-pro-preview by default.\n"
            "If INSTALL_COMMANDS=true, this command is now available:\n"
            "- /giljo — create, read, and update projects and tasks (it loads the GiljoAI guide, then acts)\n\n"
            "Restart Gemini CLI after installing commands or agents.\n\n"
            f"{_primer_persist_step('~/.gemini', 'GEMINI.md')}"
            f"{_DOWNLOAD_LINK_NOTE}"
        )
    if platform == EXPORT_ANTIGRAVITY_CLI:
        return (
            "Install the GiljoAI integration for Antigravity CLI (agy). One-time setup.\n\n"
            "agy loads agents AND skills only from an installed plugin (never loose files).\n"
            "The GiljoAI bundle is ONE plugin tree:\n"
            "  plugins/giljoai/plugin.json\n"
            "  plugins/giljoai/agents/<name>/agent.json   (nested config.customAgent)\n"
            "  plugins/giljoai/skills/<name>/SKILL.md\n\n"
            "Step 1 — Download:\n"
            f"Download: {download_url}\n"
            "Save the zip to a temp location.\n\n"
            "Step 2 — Extract the plugin tree:\n"
            "Extract the zip so the plugins/giljoai/ tree lands at\n"
            "~/.gemini/config/plugins/giljoai/ (create ~/.gemini/config/plugins/ if needed).\n"
            "Keep the nested layout — do NOT flatten agents/<name>/agent.json into loose\n"
            "files (agy will not load them). Delete the downloaded zip.\n"
            "Do NOT add experimental.enableAgents to any settings.json — that flag is\n"
            "Gemini-CLI-only and is ignored by agy.\n\n"
            "Step 3 — Validate and install the plugin:\n"
            "  agy plugin validate ~/.gemini/config/plugins/giljoai\n"
            "  agy plugin install ~/.gemini/config/plugins/giljoai\n"
            "Expect 'agents : N processed' from validate before installing.\n\n"
            "Step 4 — Connect agy to the MCP server:\n"
            "Add the GiljoAI server to ~/.gemini/config/mcp_config.json using the snippet\n"
            "from your GiljoAI server's Tools -> Connect page (Antigravity CLI).\n"
            "IMPORTANT — if migrating from Gemini CLI: agy uses the `serverUrl` field, NOT\n"
            "`url`. A leftover `url` line causes a silent failure (server lists in the UI but\n"
            "the agent cannot use it). Delete any `url` line.\n\n"
            "Adapt all commands for the OS you are running on.\n\n"
            "Step 5 — Restart Antigravity (agy). The GiljoAI agents and the $giljo skill\n"
            "are now available. To refresh agent templates later, re-run giljo_setup and\n"
            "choose the Agents only scope.\n\n"
            f"{_primer_persist_step('~/.gemini', 'GEMINI.md')}"
            f"{_DOWNLOAD_LINK_NOTE}"
        )
    if platform == EXPORT_GENERIC:
        return (
            "Your platform was not identified. To install GiljoAI agent templates\n"
            "and commands manually:\n\n"
            f"Step 1 — Download: {download_url}\n"
            "Step 2 — Extract the ZIP. It contains:\n"
            "  - agents/ — Markdown files with agent role definitions and system prompts\n"
            "  - commands/ — Reference documents describing available GiljoAI commands\n"
            "Step 3 — Install these files according to your MCP client's documentation\n"
            "  for custom agents and commands/skills.\n\n"
            "For platform-specific setup, visit your GiljoAI server's web interface\n"
            "at Tools -> Connect.\n\n"
            f"{_primer_persist_step_generic()}"
            f"{_DOWNLOAD_LINK_NOTE}"
        )
    # Fall-through default: EXPORT_CODEX_CLI ("codex_cli").
    return (
        "Install the GiljoAI CLI integration. This is a one-time setup.\n\n"
        "Step 1 — Download:\n"
        f"Download: {download_url}\n"
        "Save the zip to a temp location (do NOT extract the whole zip to ~/.codex/ yet).\n\n"
        "Step 1a — Choose install scope:\n"
        "Ask the user ONCE:\n"
        '  "What should giljo_setup install or refresh?"\n'
        "  Options: [Both skills and agents, Skills only, Agents only]\n"
        "Default to Both for first-time setup. Set INSTALL_SKILLS=true for Both or Skills only. "
        "Set INSTALL_AGENTS=true for Both or Agents only.\n\n"
        "Step 1b — Install skills if INSTALL_SKILLS=true:\n"
        "Extract only the skills/ entries from the zip into ~/.codex/skills/ "
        "(create if needed, overwrite existing). If INSTALL_SKILLS=false, do not touch "
        "~/.codex/skills/.\n\n"
        "Step 1c — Clean up legacy Codex agent registrations if INSTALL_AGENTS=true:\n"
        "Inspect ~/.codex/config.toml if it exists. If it contains any legacy "
        "[agents.gil-*] tables, back up config.toml first, then remove ONLY those "
        "GiljoAI legacy registration blocks. Preserve all non-GiljoAI agent blocks, "
        "project trust entries, MCP servers, model settings, plugins, and other user settings. "
        "Validate the edited file with a TOML parser before continuing.\n"
        "These old [agents.gil-*] blocks conflict with current standalone "
        "~/.codex/agents/gil-*.toml discovery and cause duplicate role warnings. "
        "Do not add replacement [agents.gil-*] blocks.\n"
        "If default_mode_request_user_input = true is present under [features], tell the user "
        "it is unrelated to GiljoAI agents and causes Codex's under-development warning. "
        "Remove it during this cleanup unless the user explicitly wants to keep the experimental "
        "request_user_input tool in Default mode. If INSTALL_AGENTS=false, do not touch "
        "~/.codex/config.toml unless the user explicitly asks for startup-warning cleanup.\n\n"
        "Step 1d — Install agents if INSTALL_AGENTS=true (consent required if any exist):\n"
        "Check if ~/.codex/agents/ contains any gil-*.toml files.\n"
        "If ~/.codex/agents/ contains old GiljoAI backup directories, *.bak*, or "
        "*.model-backup files, move them to ~/.codex/agent_backups/ before continuing; "
        "Codex may discover backups under ~/.codex/agents/ and report duplicate agent roles.\n"
        "  - If none exist (or the directory is missing): extract agents/* into "
        "~/.codex/agents/ and set AGENTS_INSTALLED=true.\n"
        "  - If gil-*.toml files already exist: ask the user ONCE:\n"
        '      "GiljoAI agent templates already exist in ~/.codex/agents/. '
        "Overwrite with agent templates from the server? Any local edits will be lost. "
        'Choose Skip agents to refresh skills only; re-run giljo_setup with the Agents only scope for an agent-only refresh."\n'
        "      Options: [Overwrite, Skip agents]\n"
        "    - Overwrite -> extract agents/* into ~/.codex/agents/ and set "
        "AGENTS_INSTALLED=true.\n"
        "    - Skip agents -> do NOT extract agents/*. Set AGENTS_INSTALLED=false and "
        "tell the user their existing agent files were preserved.\n"
        "If INSTALL_AGENTS=false, set AGENTS_INSTALLED=false and do not touch ~/.codex/agents/.\n\n"
        "Step 1e — Optional global AGENTS.md guidance for Codex subagent display:\n"
        "Ask the user before editing ~/.codex/AGENTS.md. This global file is the Codex home-level "
        "instructions file; project AGENTS.md files may override or add project-specific rules.\n"
        "If approved, create a timestamped backup of ~/.codex/AGENTS.md if it exists, then add or "
        "replace only this managed block using the markers below. Write UTF-8 without BOM.\n"
        "<!-- GILJOAI_CODEX_SUBAGENT_DISPLAY_START -->\n"
        "## GiljoAI Codex Subagent Display\n\n"
        f"When spawning, waiting on, messaging, or reporting Codex subagents for {branding.PRODUCT_NAME} work, "
        "always show the human-readable dashboard agent name and Codex template name alongside the "
        "Codex runtime id.\n\n"
        "Use:\n"
        "`Waiting for <dashboard-display-name> / <codex-template-name> (<codex-agent-id-short>)`\n\n"
        "Examples:\n"
        "`Waiting for tester / gil-tester (019e74bb...)`\n"
        "`Waiting for pipeline-implementer / gil-implementer-devops (019e74bb...)`\n\n"
        "Dashboard initials such as `TE` or `PI` are badges only; do not use them as the primary name.\n"
        "<!-- GILJOAI_CODEX_SUBAGENT_DISPLAY_END -->\n\n"
        "Step 1f — Clean up:\n"
        "Delete the downloaded zip.\n\n"
        "Step 2 — Leave Codex feature flags alone except the legacy cleanup above:\n"
        "Current Codex releases load subagent workflows by default. Do NOT add "
        "default_mode_request_user_input or multi_agent to ~/.codex/config.toml for this setup. "
        "default_mode_request_user_input is still an under-development feature and is only useful "
        "when the user specifically wants the experimental request_user_input tool in Default mode.\n"
        "Only read ~/.codex/config.toml if the user asks you to tune global [agents] settings such "
        "as max_threads or max_depth. If you write config.toml, use a TOML parser, preserve existing "
        "settings and non-GiljoAI agents, back up first, and write UTF-8 without BOM.\n\n"
        "Adapt all commands for the OS you are running on.\n\n"
        "Step 3 — Tell the user:\n"
        "Report exactly which scope was installed. If INSTALL_SKILLS=true, GiljoAI Codex skills "
        "were installed to ~/.codex/skills/. "
        "If AGENTS_INSTALLED=true, GiljoAI Codex agents were installed as standalone TOML "
        "files in ~/.codex/agents/. They inherit the parent Codex session model and reasoning "
        "effort unless the user later edits an agent file to add explicit overrides. "
        "If AGENTS_INSTALLED=false, existing agent files were preserved.\n"
        "If INSTALL_SKILLS=true, this skill is now available:\n"
        "- $giljo — create, read, and update projects and tasks (it loads the GiljoAI guide, then acts)\n\n"
        "Restart Codex CLI. Re-run giljo_setup with the Agents only scope for agent-only refreshes; "
        "run giljo_setup again when GiljoAI skills need updating.\n\n"
        f"{_primer_persist_step('~/.codex', 'AGENTS.md')}"
        f"{_DOWNLOAD_LINK_NOTE}"
    )
