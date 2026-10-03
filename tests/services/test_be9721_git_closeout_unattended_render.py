# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.services.protocol_builder import _build_orchestrator_protocol


def _ch5(*, headless_launch: bool) -> str:
    chapters = _build_orchestrator_protocol(
        cli_mode=False,
        project_id="P",
        orchestrator_id="JOB",
        tenant_key="T",
        include_implementation_reference=True,
        tool="multi_terminal",
        git_integration_enabled=True,
        headless_launch=headless_launch,
    )
    return chapters["ch5_reference"]


def test_attended_run_still_asks_before_skipping_git() -> None:
    reference = _ch5(headless_launch=False)
    assert "STOP and ASK" in reference
    assert "git init" in reference


def test_unattended_run_carries_on_without_asking() -> None:
    reference = _ch5(headless_launch=True)
    assert "STOP and ASK" not in reference
    assert "git_commits=[]" in reference, "the unattended path must name the explicit empty list"
    assert "closeout summary" in reference, "the unattended path must say so in the closeout summary"
    assert "Never run `git init`" in reference, "git init always needs a human's yes"


def test_git_off_renders_no_git_step_either_way() -> None:
    for headless in (False, True):
        chapters = _build_orchestrator_protocol(
            cli_mode=False,
            project_id="P",
            orchestrator_id="JOB",
            tenant_key="T",
            include_implementation_reference=True,
            tool="multi_terminal",
            git_integration_enabled=False,
            headless_launch=headless,
        )
        assert "STEP 0: Git Commit" not in chapters["ch5_reference"]
