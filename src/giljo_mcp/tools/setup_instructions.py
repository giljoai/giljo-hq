# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from dataclasses import dataclass, field
from typing import Literal

from giljo_mcp import branding
from giljo_mcp.platform_registry import (
    EXPORT_CLAUDE_CODE,
    EXPORT_GENERIC,
    EXPORT_OPENCODE,
)


@dataclass(frozen=True)
class ProductBindingContext:

    phase: Literal["bound", "zero", "ambiguous"]
    product_id: str = ""
    product_name: str = ""
    products: tuple[dict, ...] = field(default_factory=tuple)


_PRODUCT_BINDING_START = "<!-- GILJO_PRODUCT_BINDING_START -->"
_PRODUCT_BINDING_END = "<!-- GILJO_PRODUCT_BINDING_END -->"


def _product_binding_block(product_name: str, product_id: str) -> str:
    return (
        f"{_PRODUCT_BINDING_START}\n"
        f'This repo is {branding.PRODUCT_NAME} product "{product_name}" (product_id: {product_id}).\n'
        "Pass this product_id on every giljo_hq call.\n"
        f"{_PRODUCT_BINDING_END}\n"
    )


def _product_binding_persist_step(product_name: str, product_id: str) -> str:
    return (
        "Step Q — Bind this repository to its Giljo HQ product:\n"
        "Add or replace ONLY the block between the markers below in this repository's "
        "CLAUDE.md AND AGENTS.md (create either file if it does not exist; touch no "
        "other content). This writes the binding into CLAUDE.md/AGENTS.md so this "
        "never asks again. Re-running giljo_setup with product_id replaces this block "
        "in place -- never append a duplicate copy.\n"
        f"{_product_binding_block(product_name, product_id)}\n"
    )


def _product_binding_zero_note() -> str:
    return (
        "No Giljo HQ product exists yet for this tenant, so this repo was not bound to "
        "one -- that is expected during onboarding and does not block this setup. "
        "Re-run giljo_setup with product_id once a product exists to bind this "
        "repository.\n\n"
    )


def _product_binding_ambiguous_note(products: tuple[dict, ...]) -> str:
    lines = "\n".join(f"- {p['name']} (id={p['id']}, active={p['is_active']})" for p in products)
    return (
        "This tenant has multiple Giljo HQ products, so this repo was NOT bound "
        "automatically:\n"
        f"{lines}\n"
        "Confirm with the user which product this repository belongs to, then re-run "
        "giljo_setup with that product_id -- it writes the binding into CLAUDE.md/"
        "AGENTS.md so this never asks again. A binding written to the wrong product "
        "is worse than no binding: never guess.\n\n"
    )


def _build_product_binding_step(product_binding: ProductBindingContext | None) -> str:
    if product_binding is None:
        return ""
    if product_binding.phase == "bound":
        return _product_binding_persist_step(product_binding.product_name, product_binding.product_id)
    if product_binding.phase == "zero":
        return _product_binding_zero_note()
    if product_binding.phase == "ambiguous":
        return _product_binding_ambiguous_note(product_binding.products)
    return ""  # pragma: no cover - exhaustive Literal, defensive only


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


_DOWNLOAD_LINK_NOTE = (
    "Note: Download link expires in 15 minutes. If it has expired, re-run giljo_setup for a fresh link."
)

_AGENT_PROFILE_NOTE = (
    "Agent templates are NOT installed as files any more: every spawned agent receives its "
    "full profile from the server when its job starts (get_job_mission's agent_profile). Do not "
    "create, edit or delete anything in an agents directory as part of this setup.\n\n"
)


def _primer_persist_step(home_dir: str, config_filename: str) -> str:
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
        "If you also have a code-memory system (e.g. a native memory tool), save "
        "the same primer there too so it surfaces on recall. If you have neither a "
        "startup context file nor a memory system, keep the primer in-context for "
        "this session.\n\n"
    )


def _primer_persist_step_generic() -> str:
    return (
        "Step P — Persist the GiljoAI primer into your durable startup context:\n"
        "Ask the user ONCE before editing any startup/context file your client "
        "reads on boot (e.g. CLAUDE.md, AGENTS.md, or your MCP client's "
        "equivalent). If approved: back up the file if it exists, then add or "
        "replace ONLY the block between the markers below (create the file if it "
        "does not exist). Write UTF-8 without BOM. Re-running giljo_setup replaces "
        "this block in place -- never append a duplicate copy.\n"
        "<!-- GILJOAI_MCP_PRIMER_START -->\n"
        f"{GILJOAI_MCP_PRIMER}"
        "<!-- GILJOAI_MCP_PRIMER_END -->\n"
        "If you also have a code-memory system (e.g. a native memory tool), save "
        "the same primer there too so it surfaces on recall. If you have neither a "
        "startup context file nor a memory system, keep the primer in-context for "
        "this session.\n\n"
    )


def build_inline_primer_note() -> str:
    return (
        f"{branding.PRODUCT_NAME} primer for your own context (this session has no startup "
        "file to write):\n"
        f"{GILJOAI_MCP_PRIMER}"
        "If you have a code-memory system (e.g. a native memory tool), save this "
        "primer there so it surfaces on recall in future sessions. Otherwise, keep "
        "it in context for this session."
    )


def _opencode_instructions(download_url: str, product_binding: ProductBindingContext | None = None) -> str:
    return (
        "Install the GiljoAI CLI integration. This is a one-time setup.\n\n"
        "Step 1 — Download:\n"
        f"Download: {download_url}\n"
        "Save the zip to a temp location (do NOT extract the whole zip into "
        "~/.config/opencode/ yet).\n\n"
        "Step 2 — Install commands:\n"
        "Extract the commands/ entries from the zip into "
        "~/.config/opencode/commands/ (create if needed, overwrite existing). The "
        "directory is PLURAL: opencode never reads ~/.config/opencode/command/, so "
        "installing there silently does nothing.\n\n"
        "Step 3 — Clean up:\n"
        "Delete the downloaded zip.\n\n"
        "Adapt all commands for the OS you are running on.\n\n"
        "Step 4 — Tell the user:\n"
        "This command is now available:\n"
        "- /giljo — create, read, and update projects and tasks (it loads the GiljoAI "
        "guide, then acts)\n\n"
        "Restart opencode after installing commands — they are read at startup.\n\n"
        f"{_AGENT_PROFILE_NOTE}"
        f"{_primer_persist_step('~/.config/opencode', 'AGENTS.md')}"
        f"{_build_product_binding_step(product_binding)}"
        f"{_DOWNLOAD_LINK_NOTE}"
    )


def build_setup_instructions(
    platform: str,
    download_url: str,
    harness: str | None = None,
    product_binding: ProductBindingContext | None = None,
) -> str:
    del harness
    if platform == EXPORT_CLAUDE_CODE:
        return (
            "Install the GiljoAI CLI integration. This is a one-time setup.\n\n"
            "Step 1 — Download:\n"
            f"Download: {download_url}\n"
            "Save the zip to a temp location (do NOT extract the whole zip to ~/.claude/ yet).\n\n"
            "Step 2 — Install commands:\n"
            "Extract the commands/ entries from the zip into ~/.claude/commands/ "
            "(create if needed, overwrite existing).\n\n"
            "Step 3 — Clean up:\n"
            "Delete the downloaded zip.\n\n"
            "Adapt all commands for the OS you are running on.\n\n"
            "Step 4 — Tell the user:\n"
            "This command is now available:\n"
            "- /giljo — create, read, and update projects and tasks (it loads the GiljoAI guide, then acts)\n\n"
            "Restart Claude Code after installing commands.\n\n"
            f"{_AGENT_PROFILE_NOTE}"
            f"{_primer_persist_step('~/.claude', 'CLAUDE.md')}"
            f"{_build_product_binding_step(product_binding)}"
            f"{_DOWNLOAD_LINK_NOTE}"
        )
    if platform == EXPORT_OPENCODE:
        return _opencode_instructions(download_url, product_binding)
    if platform == EXPORT_GENERIC:
        return (
            "Your platform was not identified. To install the GiljoAI commands manually:\n\n"
            f"Step 1 — Download: {download_url}\n"
            "Step 2 — Extract the ZIP. It contains:\n"
            "  - commands/ — Reference documents describing available GiljoAI commands\n"
            "Step 3 — Install these files according to your MCP client's documentation\n"
            "  for custom commands/skills.\n\n"
            "For platform-specific setup, visit your GiljoAI server's web interface\n"
            "at Tools -> Connect.\n\n"
            f"{_AGENT_PROFILE_NOTE}"
            f"{_primer_persist_step_generic()}"
            f"{_build_product_binding_step(product_binding)}"
            f"{_DOWNLOAD_LINK_NOTE}"
        )
    return (
        "Install the GiljoAI CLI integration. This is a one-time setup.\n\n"
        "Step 1 — Download:\n"
        f"Download: {download_url}\n"
        "Save the zip to a temp location (do NOT extract the whole zip to ~/.codex/ yet).\n\n"
        "Step 1a — Install skills:\n"
        "Extract the skills/ entries from the zip into ~/.codex/skills/ "
        "(create if needed, overwrite existing).\n\n"
        "Step 1b — Optional global AGENTS.md guidance for Codex subagent display:\n"
        "Ask the user before editing ~/.codex/AGENTS.md. This global file is the Codex home-level "
        "instructions file; project AGENTS.md files may override or add project-specific rules.\n"
        "If approved, create a timestamped backup of ~/.codex/AGENTS.md if it exists, then add or "
        "replace only this managed block using the markers below. Write UTF-8 without BOM.\n"
        "<!-- GILJOAI_CODEX_SUBAGENT_DISPLAY_START -->\n"
        "## GiljoAI Codex Subagent Display\n\n"
        f"When spawning, waiting on, messaging, or reporting Codex subagents for {branding.PRODUCT_NAME} work, "
        "always show the human-readable dashboard agent name alongside the Codex runtime id.\n\n"
        "Use:\n"
        "`Waiting for <dashboard-display-name> (<codex-agent-id-short>)`\n\n"
        "Examples:\n"
        "`Waiting for tester (019e74bb...)`\n"
        "`Waiting for pipeline-implementer (019e74bb...)`\n\n"
        "Dashboard initials such as `TE` or `PI` are badges only; do not use them as the primary name.\n"
        "<!-- GILJOAI_CODEX_SUBAGENT_DISPLAY_END -->\n\n"
        "Step 1c — Clean up:\n"
        "Delete the downloaded zip.\n\n"
        "Step 2 — Leave Codex feature flags and ~/.codex/config.toml alone:\n"
        "Current Codex releases load subagent workflows by default. Do NOT add "
        "default_mode_request_user_input or multi_agent to ~/.codex/config.toml for this setup. "
        "Only read ~/.codex/config.toml if the user asks you to tune global [agents] settings such "
        "as max_threads or max_depth. If you write config.toml, use a TOML parser, preserve existing "
        "settings, back up first, and write UTF-8 without BOM.\n\n"
        "Adapt all commands for the OS you are running on.\n\n"
        "Step 3 — Tell the user:\n"
        "GiljoAI Codex skills were installed to ~/.codex/skills/. This skill is now available:\n"
        "- $giljo — create, read, and update projects and tasks (it loads the GiljoAI guide, then acts)\n\n"
        "Restart Codex CLI. Run giljo_setup again whenever the GiljoAI skills need updating.\n\n"
        f"{_AGENT_PROFILE_NOTE}"
        f"{_primer_persist_step('~/.codex', 'AGENTS.md')}"
        f"{_build_product_binding_step(product_binding)}"
        f"{_DOWNLOAD_LINK_NOTE}"
    )
