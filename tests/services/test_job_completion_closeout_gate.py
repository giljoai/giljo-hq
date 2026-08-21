# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9153 — pure-unit coverage for the closeout-gate signal predicate + checklist.

Edition Scope: Both. These lock the public surface of
``job_completion_closeout_gate`` (the signal detector, the checklist builder, and
the documented default) without a DB — the DB-driven gate behavior lives in
``test_be9153_closeout_mode_gate`` (solo) and ``test_be9153_chain_settlement`` (chain).
"""

from __future__ import annotations

from giljo_mcp.services.job_completion_closeout_gate import (
    CLOSEOUT_MODE_DEFAULT,
    PROTECTED_SURFACE_PATTERNS,
    build_closeout_checklist,
    detect_closeout_signal,
)


def test_default_mode_is_hitl():
    # The 2026-07-12 "default on" call — encoded as the documented default.
    assert CLOSEOUT_MODE_DEFAULT == "hitl"


def test_clean_result_carries_no_signal():
    assert detect_closeout_signal({"summary": "straightforward change"}) == []
    assert detect_closeout_signal({"files_changed": ["src/giljo_mcp/tools/foo.py"]}) == []


def test_non_dict_result_is_clean():
    assert detect_closeout_signal(None) == []
    assert detect_closeout_signal("not a dict") == []
    assert detect_closeout_signal([1, 2, 3]) == []


def test_deferred_findings_is_signal():
    reasons = detect_closeout_signal({"deferred_findings": ["needs a call on retry policy"]})
    assert len(reasons) == 1 and "deferred" in reasons[0]
    # empty list is NOT signal
    assert detect_closeout_signal({"deferred_findings": []}) == []


def test_protected_surface_is_signal():
    # Realistic paths stay provider-neutral: the CE export bundle ships this file
    # and the boundary scan bans billing-provider names in CE sources.
    for path in (
        "migrations/versions/ce_0044.py",
        "src/giljo_mcp/api/auth/session.py",
        "src/giljo_mcp/licensing/validator.py",
        "src/giljo_mcp/saas/billing/invoice_service.py",
    ):
        reasons = detect_closeout_signal({"files_changed": [path]})
        assert any("protected surface" in r for r in reasons), f"expected signal for {path}"


def test_every_protected_surface_pattern_signals():
    # Full coverage of the SSoT tuple without hardcoding any entry: synthesize a
    # path around each pattern at runtime. Stays in sync when reviewers extend
    # PROTECTED_SURFACE_PATTERNS.
    for pattern in PROTECTED_SURFACE_PATTERNS:
        path = f"some/{pattern}_file.py"
        reasons = detect_closeout_signal({"files_changed": [path]})
        assert any("protected surface" in r for r in reasons), f"pattern {pattern!r} must signal"


def test_protected_surface_detected_in_commit_dicts():
    reasons = detect_closeout_signal(
        {"commits": [{"message": "fix", "files": ["src/giljo_mcp/saas/billing/reconciler.py"]}]}
    )
    assert any("protected surface" in r for r in reasons)


def test_verification_gap_is_signal():
    assert any("verification gap" in r for r in detect_closeout_signal({"tests": {"failed": 2, "skipped": 0}}))
    assert any("verification gap" in r for r in detect_closeout_signal({"tests": {"failed": 0, "skipped": 3}}))
    assert any("verification gap" in r for r in detect_closeout_signal({"verification": {"failed": 1}}))
    assert any("verification gap" in r for r in detect_closeout_signal({"verification_gaps": ["flaky reaper test"]}))
    # all-green tests are NOT signal
    assert detect_closeout_signal({"tests": {"failed": 0, "skipped": 0}}) == []


def test_malformed_test_counts_do_not_crash():
    # non-numeric counts are tolerated (never raises), producing no signal.
    assert detect_closeout_signal({"tests": {"failed": "oops", "skipped": None}}) == []


def test_multiple_signals_accumulate():
    reasons = detect_closeout_signal(
        {
            "deferred_findings": ["x"],
            "files_changed": ["migrations/versions/ce_0045.py"],
            "tests": {"failed": 1},
        }
    )
    assert len(reasons) == 3


def test_protected_surface_patterns_is_the_single_source():
    # rider (a): reviewers extend the surface list HERE; lock the load-bearing members.
    for pat in ("migrations/", "billing", "oauth", "password", "licensing"):
        assert pat in PROTECTED_SURFACE_PATTERNS


def test_checklist_surfaces_mode_and_gate():
    hitl = build_closeout_checklist("hitl")
    assert hitl["closeout_mode"] == "hitl"
    assert "request_approval" in hitl["instruction"]
    assert "deferred_findings" in hitl["instruction"]  # names the signal keys (instruction-loop repair)

    auto = build_closeout_checklist("autonomous")
    assert auto["closeout_mode"] == "autonomous"
    assert "without an approval gate" in auto["instruction"]

    # default arg == the documented default
    assert build_closeout_checklist()["closeout_mode"] == "hitl"
