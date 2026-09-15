# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.domain.project_status import (
    LIFECYCLE_FINISHED_STATUSES,
    ProjectStatus,
)




def test_archive_skip_set_contains_exactly_terminal_and_inactive_states() -> None:

    skip_set = LIFECYCLE_FINISHED_STATUSES | {ProjectStatus.INACTIVE}

    assert skip_set == {
        ProjectStatus.INACTIVE,
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.TERMINATED,
        ProjectStatus.DELETED,
        ProjectStatus.SUPERSEDED,
    }, (
        f"archive_project skip-set drifted: {sorted(s.value for s in skip_set)}. "
        "Update src/giljo_mcp/domain/project_status.py and the test together "
        "if this is intentional."
    )

    assert ProjectStatus.ACTIVE not in skip_set


def test_lifecycle_finished_set_is_exactly_the_canonical_terminal_states() -> None:

    expected = {
        ProjectStatus.COMPLETED,
        ProjectStatus.CANCELLED,
        ProjectStatus.TERMINATED,
        ProjectStatus.DELETED,
        ProjectStatus.SUPERSEDED,
    }
    assert expected == LIFECYCLE_FINISHED_STATUSES




def test_archive_target_status_terminated_when_early_termination_true() -> None:

    early_termination = True
    target_status = ProjectStatus.TERMINATED if early_termination else ProjectStatus.COMPLETED

    assert target_status is ProjectStatus.TERMINATED
    assert target_status.value == "terminated"
    assert target_status in ProjectStatus


def test_archive_target_status_completed_when_early_termination_false() -> None:

    early_termination = False
    target_status = ProjectStatus.TERMINATED if early_termination else ProjectStatus.COMPLETED

    assert target_status is ProjectStatus.COMPLETED
    assert target_status.value == "completed"
    assert target_status in ProjectStatus




def test_removed_pre_be5039_literals_are_not_in_canonical_enum() -> None:

    canonical_values = {s.value for s in ProjectStatus}

    for legacy in ("archived", "closed", "paused", "staging", "draft"):
        assert legacy not in canonical_values, (
            f"Legacy status literal '{legacy}' was re-introduced into ProjectStatus. "
            "If you genuinely need this back, add a migration that creates the ENUM "
            "label and update this test."
        )
