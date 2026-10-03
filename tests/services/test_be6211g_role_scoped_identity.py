# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import hashlib

from giljo_mcp.template_seeder import (
    _get_orchestrator_system_harness,
    compose_orchestrator_identity,
)


_TOOLS = ("multi_terminal", "claude-code", "codex", "gemini", "antigravity")

_SOLO_IDENTITY_SHA256 = {
    "multi_terminal": "0bc366db86e22345a835c0ef603c427dbc76eb55ac4bfa67c334a07431936c02",
    "claude-code": "c150b73889953a9e747dcd756c02d4b393ec61eaa0a99e1f70964c8db671e4cc",
    "codex": "0bc366db86e22345a835c0ef603c427dbc76eb55ac4bfa67c334a07431936c02",
    "gemini": "0bc366db86e22345a835c0ef603c427dbc76eb55ac4bfa67c334a07431936c02",
    "antigravity": "0bc366db86e22345a835c0ef603c427dbc76eb55ac4bfa67c334a07431936c02",
}

_BEFORE_CLOSEOUT = "## Before Closeout"
_RESPONDING = "### RESPONDING TO CONTEXT REQUESTS"
_SPAWN_JOB_BULLET = "- `spawn_job`:"
_REPORT_PROGRESS_BULLET = "- `report_progress`:"
_COORDINATION_PRINCIPLES = "## ORCHESTRATOR COORDINATION PRINCIPLES"
_THREE_PHASE = "## Three-Phase Workflow"
_CORE_RESPONSIBILITIES = "## Core Responsibilities"
_BEHAVIORAL_PRINCIPLES = "## Behavioral Principles"
_IF_REQUIREMENTS = "## If Requirements Are Unclear"
_RIGHT_SIZING = "## Right-Sizing Your Work"




def test_identity_default_equals_explicit_role_none_all_tools() -> None:
    for tool in _TOOLS:
        assert compose_orchestrator_identity(None, tool=tool) == compose_orchestrator_identity(
            None, tool=tool, role=None
        )
        assert compose_orchestrator_identity("CUSTOM SEED", tool=tool) == compose_orchestrator_identity(
            "CUSTOM SEED", tool=tool, role=None
        )


def test_solo_identity_frozen_sha256_golden() -> None:
    for tool, expected in _SOLO_IDENTITY_SHA256.items():
        actual = hashlib.sha256(compose_orchestrator_identity(None, tool=tool).encode("utf-8")).hexdigest()
        assert actual == expected, f"solo identity bytes drifted for tool={tool!r}"


def test_suborch_role_keeps_full_seed_byte_identical_to_solo() -> None:
    for tool in _TOOLS:
        assert compose_orchestrator_identity(None, tool=tool, role="sub_orchestrator") == compose_orchestrator_identity(
            None, tool=tool
        )




def test_conductor_role_trims_identity_blocks() -> None:
    cond = compose_orchestrator_identity(None, tool="multi_terminal", role="conductor")
    assert _THREE_PHASE not in cond, "conductor identity must drop '## Three-Phase Workflow' (solo single-project flow)"
    assert _CORE_RESPONSIBILITIES not in cond, "conductor identity must drop '## Core Responsibilities' (solo)"
    assert _IF_REQUIREMENTS not in cond, (
        "conductor identity must drop '## If Requirements Are Unclear' (solo staging-lock/request_approval flow)"
    )
    assert _BEFORE_CLOSEOUT not in cond, (
        "conductor identity must drop the verify-all-agents '## Before Closeout' finale"
    )
    assert _RESPONDING not in cond, "conductor identity must drop '### RESPONDING TO CONTEXT REQUESTS'"
    assert _SPAWN_JOB_BULLET not in cond, "conductor identity must drop the worker-spawn 'spawn_job' tool-index bullet"
    assert _BEHAVIORAL_PRINCIPLES in cond, "the '## Behavioral Principles' END anchor (slice C) must be retained"
    assert _RIGHT_SIZING in cond, "the '## Right-Sizing Your Work' END anchor (slice D) must be retained"
    assert _COORDINATION_PRINCIPLES in cond, "the coordination-principles END anchor (slice A) must be retained"
    assert _REPORT_PROGRESS_BULLET in cond, "the report_progress bullet (slice B END anchor) must be retained"
    assert _get_orchestrator_system_harness(tool="multi_terminal").strip() in cond, (
        "the conductor must keep the full system harness (tool gating + check-in)"
    )


def test_conductor_identity_diff_is_exactly_the_trims_reverse_splice() -> None:
    solo = compose_orchestrator_identity(None, tool="multi_terminal")
    cond = compose_orchestrator_identity(None, tool="multi_terminal", role="conductor")

    spans = [
        (_THREE_PHASE, _BEHAVIORAL_PRINCIPLES),
        (_IF_REQUIREMENTS, _RIGHT_SIZING),
        (_BEFORE_CLOSEOUT, _COORDINATION_PRINCIPLES),
        (_SPAWN_JOB_BULLET, _REPORT_PROGRESS_BULLET),
    ]

    restored = cond
    for start_anchor, end_anchor in spans:
        start = solo.find(start_anchor)
        end = solo.find(end_anchor)
        assert start != -1 and end != -1 and start < end, (
            f"anchor pair not found/ordered: {start_anchor!r}..{end_anchor!r}"
        )
        assert solo.count(end_anchor) == 1, f"END anchor not unique in solo: {end_anchor!r}"
        assert cond.count(end_anchor) == 1, f"END anchor not unique in conductor identity: {end_anchor!r}"
        span = solo[start:end]
        restored = restored.replace(end_anchor, span + end_anchor, 1)

    assert restored == solo, "conductor trim must remove ONLY the four anchored spans, nothing else"


def test_conductor_role_noops_on_admin_override_lacking_anchors() -> None:
    override = "CUSTOM CONDUCTOR SEED — a bespoke tenant override with none of the default headings."
    with_role = compose_orchestrator_identity(override, tool="multi_terminal", role="conductor")
    without_role = compose_orchestrator_identity(override, tool="multi_terminal", role=None)
    assert with_role == without_role, "conductor trim must be a graceful no-op when the override lacks the anchors"
    assert "CUSTOM CONDUCTOR SEED" in with_role
