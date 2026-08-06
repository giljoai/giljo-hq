# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-6211g move (c) — role-scoped orchestrator identity.

``compose_orchestrator_identity`` gains an OPTIONAL ``role`` param. Its DEFAULT
(``role=None``, the value produced for every solo / sub_orchestrator path)
reproduces today's seed byte-for-byte — the #1 risk control for SOLO-IS-SACRED.
``role="conductor"`` trims the project-less chain conductor of the solo-orchestration
blocks it must not act on. BE-6211g removed three (RESPONDING TO CONTEXT REQUESTS, the
verify-all-agents "## Before Closeout" finale, the worker-spawn ``spawn_job`` bullet);
BE-6215 extends the trim with the single-project solo flows (## Three-Phase Workflow +
## Core Responsibilities, and ## If Requirements Are Unclear) — FOUR anchored spans
total, leaving the coordination principles, right-sizing, tool index + system harness
untouched. The reverse-splice guard is rewritten to pin the new 4-span set exactly.

Pure tests (no DB, no module-level mutable state) — parallel-safe under xdist.
Edition Scope: CE.
"""

from __future__ import annotations

import hashlib

from giljo_mcp.template_seeder import (
    _get_orchestrator_system_harness,
    compose_orchestrator_identity,
)


# All FIVE tool_types in EXECUTION_MODE_TO_TOOL (antigravity included — it flows
# through compose_orchestrator_identity(tool=...) like any other CLI mode).
_TOOLS = ("multi_terminal", "claude-code", "codex", "gemini", "antigravity")

# Frozen golden — sha256 of the DEFAULT (no-role) composed solo identity per tool.
# This is the byte-identity lock: it flips RED if the conductor trim ever leaks into
# the role=None default path or the seed text drifts. multi_terminal/codex/gemini/
# antigravity share a hash (the harness only branches for claude-code's HARNESS
# REMINDER OVERRIDE). BE-9012d re-froze it after a deliberate seed edit: the bus
# (send_message/receive_messages) references in the seed's "Technical Environment",
# "If Requirements Are Unclear", "Non-obvious Tool Parameters", "Before Closeout", and
# "RESPONDING TO CONTEXT REQUESTS" sections were converted to the Hub
# (post_to_thread/get_thread_history) — the bus is retired. git-verified that this is
# the ONLY change to the composed identity.
#
# BE-9012d (Phase 4a-2, F1): re-frozen AGAIN — ``_get_mcp_coordination_section()``
# (part of ``_get_orchestrator_system_harness``) had its example tool call
# bare-ified (``get_job_mission(job_id="...")`` instead of the
# ``mcp__giljo_mcp__``-prefixed form) and gained the "tool names below are bare"
# client-prefix note, since this harness section renders to Codex/Gemini/Desktop
# too, where the Claude Code prefix is wrong. git-verified (diff of the composed
# identity for both a shared-hash tool and claude-code) that this is the ONLY
# change — nothing else in the seed or harness moved.
#
# BE-9058: re-frozen after the deliberate agent-prose sweep — the seed's
# "Non-obvious Tool Parameters" complete_job bullet no longer teaches the RETIRED
# acknowledge flags (BE-9012b retired them server-side; the old bullet was no-op
# advice). git-verified that this seed bullet is the ONLY change to the composed
# identity (the sweep's other edits live in the protocol chapters, not the seed).
#
# BE-9259: re-frozen after the persona-neutralization sweep — two internal-process
# phrases in the orchestrator seed were customer-neutralized: the "## Success
# Criteria" bullet ("Handover documentation complete and actionable" -> "Project
# documentation kept current and actionable") and the "## If Requirements Are
# Unclear" section dropped its internal ticket citation ("that pattern predates
# BE-5029 and shows as..." -> "that shows as..."). git-verified (diff of
# src/giljo_mcp/template_seeder.py) that these two lines are the ONLY change to
# the composed identity — the tester/implementer/documenter persona rewrites in
# the same change live in separate, non-orchestrator template defs.
# BE-9275b: re-frozen after the HQ rebrand heading edit — the seed's opening
# heading ("# GiljoAI MCP Agent" -> "# Giljo HQ Agent") is the ONLY change to
# the composed identity (git-verified: `f"# {PRODUCT_NAME} Agent"` derives from
# branding.py; the "for **GiljoAI MCP**" body sentence is untouched, out of
# this chain step's scope).
# BE-9361: re-frozen after the rename-residuals sweep finished what BE-9275b
# left — the body sentence above ("for **GiljoAI MCP**" -> "for **Giljo HQ**",
# now derived from branding.PRODUCT_NAME via _ORCHESTRATOR_IDENTITY_HEAD) is the
# ONLY change to the composed identity. Verified by reverse substitution, not by
# reading the diff: replacing just that one name substring back in the newly
# composed text reproduces the previous golden EXACTLY for all five tools, which
# is only possible if nothing else moved.
_SOLO_IDENTITY_SHA256 = {
    "multi_terminal": "3b17f3ff087b11d7a6481695342770f289bb3d9d5b4ae7d4aa3c1255b31eb8e1",
    "claude-code": "bbfc8c66cd180fdc57ddc2592376b8dc04b0e58b9b36235b02fc4ed4eb966f96",
    "codex": "3b17f3ff087b11d7a6481695342770f289bb3d9d5b4ae7d4aa3c1255b31eb8e1",
    "gemini": "3b17f3ff087b11d7a6481695342770f289bb3d9d5b4ae7d4aa3c1255b31eb8e1",
    "antigravity": "3b17f3ff087b11d7a6481695342770f289bb3d9d5b4ae7d4aa3c1255b31eb8e1",
}

# Verbatim seed anchors the conductor trim removes / retains.
_BEFORE_CLOSEOUT = "## Before Closeout"
_RESPONDING = "### RESPONDING TO CONTEXT REQUESTS"
_SPAWN_JOB_BULLET = "- `spawn_job`:"
_REPORT_PROGRESS_BULLET = "- `report_progress`:"
_COORDINATION_PRINCIPLES = "## ORCHESTRATOR COORDINATION PRINCIPLES"
# BE-6215 — two additional solo-flow spans the conductor trim removes / retains.
_THREE_PHASE = "## Three-Phase Workflow"
_CORE_RESPONSIBILITIES = "## Core Responsibilities"
_BEHAVIORAL_PRINCIPLES = "## Behavioral Principles"  # SLICE C END anchor (kept)
_IF_REQUIREMENTS = "## If Requirements Are Unclear"
_RIGHT_SIZING = "## Right-Sizing Your Work"  # SLICE D END anchor (kept)


# ---------------------------------------------------------------------------
# Default (role=None) is byte-identical to today — the #1 risk control.
# ---------------------------------------------------------------------------


def test_identity_default_equals_explicit_role_none_all_tools() -> None:
    """The new param is inert by default: omitting role == passing role=None, for
    every tool and both override states (None seed and a custom admin override)."""
    for tool in _TOOLS:
        assert compose_orchestrator_identity(None, tool=tool) == compose_orchestrator_identity(
            None, tool=tool, role=None
        )
        assert compose_orchestrator_identity("CUSTOM SEED", tool=tool) == compose_orchestrator_identity(
            "CUSTOM SEED", tool=tool, role=None
        )


def test_solo_identity_frozen_sha256_golden() -> None:
    """The DEFAULT composed identity is byte-frozen to its HEAD golden per tool.
    Flips RED if any trim leaks into the role=None path or the seed text drifts."""
    for tool, expected in _SOLO_IDENTITY_SHA256.items():
        actual = hashlib.sha256(compose_orchestrator_identity(None, tool=tool).encode("utf-8")).hexdigest()
        assert actual == expected, f"solo identity bytes drifted for tool={tool!r}"


def test_suborch_role_keeps_full_seed_byte_identical_to_solo() -> None:
    """role='sub_orchestrator' is treated as None (no trim): a sub-orch closes out
    its OWN project and spawns its OWN workers, so it keeps the full solo seed."""
    for tool in _TOOLS:
        assert compose_orchestrator_identity(None, tool=tool, role="sub_orchestrator") == compose_orchestrator_identity(
            None, tool=tool
        )


# ---------------------------------------------------------------------------
# role='conductor' trims exactly the three blocks, nothing else.
# ---------------------------------------------------------------------------


def test_conductor_role_trims_identity_blocks() -> None:
    """role='conductor' removes the FIVE solo-orchestration blocks (BE-6211g + BE-6215):
    Three-Phase Workflow + Core Responsibilities (slice C), If-Requirements (slice D),
    the verify-all-agents finale + RESPONDING TO CONTEXT REQUESTS (slice A), and the
    spawn_job bullet (slice B); keeps every END anchor + the coordination principles +
    right-sizing + tool index + harness."""
    cond = compose_orchestrator_identity(None, tool="multi_terminal", role="conductor")
    # BE-6215 slices C + D — the single-project solo flows.
    assert _THREE_PHASE not in cond, "conductor identity must drop '## Three-Phase Workflow' (solo single-project flow)"
    assert _CORE_RESPONSIBILITIES not in cond, "conductor identity must drop '## Core Responsibilities' (solo)"
    assert _IF_REQUIREMENTS not in cond, (
        "conductor identity must drop '## If Requirements Are Unclear' (solo staging-lock/request_approval flow)"
    )
    # BE-6211g slices A + B.
    assert _BEFORE_CLOSEOUT not in cond, (
        "conductor identity must drop the verify-all-agents '## Before Closeout' finale"
    )
    assert _RESPONDING not in cond, "conductor identity must drop '### RESPONDING TO CONTEXT REQUESTS'"
    assert _SPAWN_JOB_BULLET not in cond, "conductor identity must drop the worker-spawn 'spawn_job' tool-index bullet"
    # Retained END anchors of every slice + the load-bearing kept sections.
    assert _BEHAVIORAL_PRINCIPLES in cond, "the '## Behavioral Principles' END anchor (slice C) must be retained"
    assert _RIGHT_SIZING in cond, "the '## Right-Sizing Your Work' END anchor (slice D) must be retained"
    assert _COORDINATION_PRINCIPLES in cond, "the coordination-principles END anchor (slice A) must be retained"
    assert _REPORT_PROGRESS_BULLET in cond, "the report_progress bullet (slice B END anchor) must be retained"
    # The system harness (MCP Tool Usage + CHECK-IN PROTOCOL) is NEVER trimmed.
    assert _get_orchestrator_system_harness(tool="multi_terminal").strip() in cond, (
        "the conductor must keep the full system harness (tool gating + check-in)"
    )


def test_conductor_identity_diff_is_exactly_the_trims_reverse_splice() -> None:
    """Reverse-splice proof (BE-6215): re-inserting ONLY the four removed verbatim spans
    back into the conductor identity, each at its kept END anchor, reproduces the solo
    identity byte-for-byte — so the trim removed EXACTLY those four spans and nothing
    else. This guard is the no-instruction-lost lock; it is rewritten to pin the new
    (4-span) trim set and is NOT loosened (each span is sliced from the live solo seed
    by its real anchors, and every END anchor is asserted unique/ordered before use)."""
    solo = compose_orchestrator_identity(None, tool="multi_terminal")
    cond = compose_orchestrator_identity(None, tool="multi_terminal", role="conductor")

    # Each removed span = solo[START_anchor : END_anchor]; END anchor kept in cond.
    # Listed in seed (document) order; every anchor must be present, unique, and ordered.
    spans = [
        # Span C: '## Three-Phase Workflow' .. '## Behavioral Principles' (Three-Phase + Core Responsibilities).
        (_THREE_PHASE, _BEHAVIORAL_PRINCIPLES),
        # Span D: '## If Requirements Are Unclear' .. '## Right-Sizing Your Work'.
        (_IF_REQUIREMENTS, _RIGHT_SIZING),
        # Span A: '## Before Closeout' .. '## ORCHESTRATOR COORDINATION PRINCIPLES' (Before Closeout + RESPONDING).
        (_BEFORE_CLOSEOUT, _COORDINATION_PRINCIPLES),
        # Span B: '- `spawn_job`:' .. '- `report_progress`:'.
        (_SPAWN_JOB_BULLET, _REPORT_PROGRESS_BULLET),
    ]

    restored = cond
    for start_anchor, end_anchor in spans:
        start = solo.find(start_anchor)
        end = solo.find(end_anchor)
        assert start != -1 and end != -1 and start < end, (
            f"anchor pair not found/ordered: {start_anchor!r}..{end_anchor!r}"
        )
        # Each END anchor must be unique in solo AND in cond so the splice is unambiguous.
        assert solo.count(end_anchor) == 1, f"END anchor not unique in solo: {end_anchor!r}"
        assert cond.count(end_anchor) == 1, f"END anchor not unique in conductor identity: {end_anchor!r}"
        span = solo[start:end]
        restored = restored.replace(end_anchor, span + end_anchor, 1)

    assert restored == solo, "conductor trim must remove ONLY the four anchored spans, nothing else"


def test_conductor_role_noops_on_admin_override_lacking_anchors() -> None:
    """A custom admin-override seed without the default headings -> the conductor trim
    finds no anchors and gracefully no-ops (the override+harness is returned unchanged).
    Seam reconciliation for such a tenant then comes from the move-(a) preamble and the
    move-(b) body trim, not the identity trim. Documented behavior, pinned here."""
    override = "CUSTOM CONDUCTOR SEED — a bespoke tenant override with none of the default headings."
    with_role = compose_orchestrator_identity(override, tool="multi_terminal", role="conductor")
    without_role = compose_orchestrator_identity(override, tool="multi_terminal", role=None)
    assert with_role == without_role, "conductor trim must be a graceful no-op when the override lacks the anchors"
    assert "CUSTOM CONDUCTOR SEED" in with_role
