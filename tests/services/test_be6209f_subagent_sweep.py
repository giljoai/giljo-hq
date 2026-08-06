# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6209f — complete the subagent-mode protocol conditioning sweep (6209c Q1 was partial).

6209c Q1 conditioned three BODY fragments, but the rendered orchestrator payload for a
Claude Code subagent STILL carried multi-terminal-ONLY operating instructions that the
mode flag did not strip:

  * agent_lifecycle.py "Unblock an agent" relay step — ``Tell user: "Go to that agent's
    terminal and say: the orchestrator responded"`` (a separate-terminal nudge a subagent
    orchestrator cannot give).
  * agent_lifecycle.py verification-launch — the ``Multi-terminal: ... start it from the
    dashboard.`` bullet.
  * chapters_reference.py CH3 SUBAGENT-MODE NOTE — the trailing ``...dashboard Play
    buttons; subagent modes do not.`` contrast naming a multi-terminal mechanism.

These are now conditioned on the canonical ``is_subagent_render`` registry signal
(``Platform.is_subagent``) — the SAME source of truth the 6209c Q1 body predicate and the
FORBIDDEN banner now use (no more scattered ``execution_mode != MULTI_TERMINAL`` compares).

Invariant locked here: the multi_terminal render stays BYTE-IDENTICAL to a pre-change
golden (``_be6209f_golden_multi_terminal.txt``). Strings already conditioned via the
existing per-tool dispatch (reactivation block, generic CH3, ``locked Play button``) are
also asserted absent from the subagent render, locking the dispatch against regression.

Scope note: genuinely-UNKNOWN tools (and ``antigravity``, which lacks a dedicated CH3 /
reactivation dispatch entry) fall back to the HO1020 platform-neutral generic block, whose
"operator pastes the thin prompt" framing is the intended fail-safe for a tool the server
has no spawn syntax for — NOT in scope here. This sweep covers the registered subagent
tools that have dedicated dispatch blocks (claude-code / codex / gemini).

Pure-string assertions (no DB, no module-level mutable state) — parallel-safe.
Edition Scope: CE.
"""

from __future__ import annotations

from pathlib import Path

from giljo_mcp.platform_registry import is_subagent_render
from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol
from giljo_mcp.services.protocol_sections.agent_protocol import _generate_agent_protocol


_GOLDEN = Path(__file__).parent / "_be6209f_golden_multi_terminal.txt"

# Registered subagent tool_types that have dedicated CH3 + reactivation dispatch blocks.
# (antigravity is intentionally excluded — see module docstring scope note.)
_SUBAGENT_TOOLS = ("claude-code", "codex", "gemini")

# Multi-terminal-ONLY operating strings that must NEVER appear in a subagent render.
# The first three are this project's newly-conditioned fragments; the rest were already
# conditioned via per-tool dispatch and are pinned here to lock that dispatch.
_MULTI_TERMINAL_ONLY = (
    "Go to that agent's terminal",  # body: Unblock-an-agent relay (BE-6209f)
    "start it from the dashboard",  # body: verification-launch multi-terminal bullet (BE-6209f)
    "dashboard Play buttons",  # CH3 SUBAGENT-MODE NOTE contrast tail (BE-6209f)
    "Open a new session with your AI and paste this prompt",  # reactivation block (dispatch, BE-8003h)
    "locked Play button",  # CH_AUTHORITY multi_terminal branch (dispatch)
    "Copy agent prompts from the dashboard to start them.",  # body phase-1 (6209c Q1)
    "Tell user to paste the new prompt in a NEW terminal",  # body replacement (6209c Q1)
    "**If waiting for user to start agents (multi-terminal):**",  # body resting (6209c Q1)
)


def _render(*, tool: str, exec_mode: str, staging: bool, conductor: bool = False) -> str:
    """Render the full orchestrator payload (every chapter + the full_protocol body),
    mirroring how mission_service assembles them.

    The body's ``execution_mode`` parameter receives the tool_type, matching the real
    mission_service conflation (``agent_tool`` is passed as BOTH execution_mode and tool).
    """
    chapters = _build_orchestrator_protocol(
        cli_mode=(tool != "multi_terminal"),
        project_id="PID-golden",
        orchestrator_id="OID-golden",
        tenant_key="TK-golden",
        include_implementation_reference=not staging,
        tool=tool,
    )
    body = _generate_agent_protocol(
        job_id="JID-golden",
        tenant_key="TK-golden",
        agent_name="orchestrator",
        agent_id="AID-golden",
        execution_mode=exec_mode,
        job_type="orchestrator",
        tool=tool,
        is_chain_conductor=conductor,
    )
    parts: list[str] = []
    for key, value in chapters.items():
        parts.append(f"<<<CHAPTER:{key}>>>")
        parts.append(str(value))
    parts.append("<<<BODY>>>")
    parts.append(body)
    return "\n".join(parts)


def _multi_terminal_golden_render() -> str:
    """Reproduce the exact composition used to capture the golden (impl + staging)."""
    blocks: list[str] = []
    for staging in (False, True):
        tag = "STAGING" if staging else "IMPL"
        blocks.append(f"########## MULTI_TERMINAL {tag} ##########")
        blocks.append(_render(tool="multi_terminal", exec_mode="multi_terminal", staging=staging))
    return "\n".join(blocks)


# --- RED-GREEN: subagent render carries NO multi-terminal-only operating strings -------


def test_subagent_render_has_no_multi_terminal_only_strings() -> None:
    """The whole orchestrator payload (chapters + body), staging AND implementation, for
    every registered subagent tool, is free of multi-terminal-only operating prose."""
    for tool in _SUBAGENT_TOOLS:
        for staging in (False, True):
            rendered = _render(tool=tool, exec_mode=tool, staging=staging)
            for needle in _MULTI_TERMINAL_ONLY:
                assert needle not in rendered, (
                    f"{tool} ({'staging' if staging else 'impl'}) leaked multi-terminal-only string: {needle!r}"
                )


def test_newly_conditioned_strings_present_in_multi_terminal() -> None:
    """No-regression: the multi_terminal render KEEPS the three BE-6209f fragments verbatim
    (they are stripped only for subagent modes, never deleted outright)."""
    multi = _render(tool="multi_terminal", exec_mode="multi_terminal", staging=False)
    assert "Go to that agent's terminal and say: the orchestrator responded" in multi
    assert "Verification agent spawned, start it from the dashboard." in multi
    assert "Multi-terminal mode gates on\nphase via the dashboard Play buttons; subagent modes do not." in multi


def test_subagent_self_spawn_phrasing_replaces_the_relay_line() -> None:
    """The subagent render swaps the separate-terminal relay nudge for inbox/self-spawn
    phrasing that agrees with the subagent wake block.

    BE-9012d: the bus (receive_messages) is retired in favor of the Hub
    (get_thread_history poll on the coordination thread)."""
    sub = _render(tool="claude-code", exec_mode="claude-code", staging=False)
    assert "reads your reply on its next get_thread_history poll" in sub
    # The verification-launch keeps the subagent half (its first call binds the record).
    assert "its VERY FIRST call MUST be" in sub


# --- Byte-identical no-regression lock on the multi_terminal render --------------------


def test_multi_terminal_render_is_byte_identical_to_golden() -> None:
    """Lock: the multi_terminal render (impl + staging, all chapters + body) is unchanged
    byte-for-byte from the pre-BE-6209f golden. Catches any accidental drift in the
    human-driven mode.

    BE-9012d re-froze this golden after a deliberate prose sweep: the bus
    (send_message/receive_messages) was retired in favor of the Hub
    (post_to_thread/get_thread_history), and bare (unprefixed) tool names replaced the
    hardcoded `mcp__giljo_mcp__` prefix in this harness-neutral render. git-verified that
    those are the ONLY changes to the golden.

    BE-9012d (Phase 4a-2): re-frozen AGAIN for a pre-existing, unrelated bug fix --
    orchestrator_body.py's closeout-checklist f-string had a literal `{id}` that Python
    interpolated as the `id` builtin (rendering "POST /api/approvals/<built-in function
    id>/decide"); escaped to the literal `{{id}}` placeholder. git-verified that is the
    ONLY change to the golden.

    BE-9260: re-frozen for the protocol-section neutrality sweep -- orchestrator_body.py's
    non-blocking-findings triage bullets stopped mandating THIS repo's pytest/ruff toolchain,
    'master' as THE branch, and this repo's hardcoded protected-file list, wording them
    product-derived instead. git-verified that reword (appearing twice, IMPL + STAGING) is
    the ONLY change to the golden -- the orchestrator render never mentioned TodoWrite, so
    this golden is untouched by the harness-neutral task-list phrasing changes elsewhere.

    BE-9256: re-frozen for the closeout git_commits fail-closed-on-missing-title project --
    chapters_reference.py's worked-example key_outcomes dropped the "BE-5025 closed clean"
    internal ticket ref (neutrality guard baseline entry, also removed) in favor of a
    product-neutral outcome string. diff-verified that single line is the ONLY change to
    the golden.

    BE-9292b: re-frozen for the stalled-agent terminal-state project -- chapters_reference.py
    gained an "ACCEPTING A STALLED AGENT" subsection under CLOSING JOBS, telling the
    orchestrator to complete_job + close_job a 'silent' agent whose deliverable it verified
    instead of force-decommissioning it (which mislabels accepted work as failed). Purely
    additive: diff-verified as 25 inserted lines and ZERO deletions or modifications.

    TSK-9314: re-frozen for the neutrality-baseline cleanup -- chapters_reference.py's
    AGENT REACTIVATION PROTOCOL heading and its auto-block sentence dropped the two
    internal handover numbers ("Handover 0435c" / "Handover 0827b", both neutrality
    guard baseline entries, both removed) that a customer cannot dereference. Same shape
    as the BE-9256 re-freeze above. diff-verified as exactly 2 changed lines, both
    citation removals, with no other edit and no line-ending change."""
    golden = _GOLDEN.read_text(encoding="utf-8")
    assert _multi_terminal_golden_render() == golden


# --- Canonical predicate: ONE source of truth -----------------------------------------


def test_is_subagent_render_is_the_canonical_signal() -> None:
    """The registry signal resolves either identity axis (execution_mode OR tool_type),
    treats multi_terminal/empty as non-subagent, and fails an unknown CLI safe to
    subagent (so multi-terminal prose is never leaked into an unrecognized tool)."""
    # multi_terminal / empty → not a subagent render
    assert is_subagent_render("multi_terminal") is False
    assert is_subagent_render("") is False
    assert is_subagent_render(None) is False
    # registered, by execution_mode
    assert is_subagent_render("claude_code_cli") is True
    assert is_subagent_render("codex_cli") is True
    # registered, by tool_type (the mission_service-conflated value)
    assert is_subagent_render("claude-code") is True
    assert is_subagent_render("gemini") is True
    # unknown non-empty → subagent (fail safe, never a multi-terminal leak)
    assert is_subagent_render("some_future_cli") is True
