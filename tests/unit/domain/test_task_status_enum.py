# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.domain.task_status import (
    TASK_LIFECYCLE_FINISHED_STATUSES,
    TASK_STATUS_META,
    VALID_TASK_STATUSES,
    TaskStatus,
    TaskStatusMeta,
)




def test_enum_has_exactly_six_members() -> None:

    assert {s.value for s in TaskStatus} == {
        "pending",
        "in_progress",
        "on_hold",
        "completed",
        "blocked",
        "cancelled",
    }


def test_enum_declaration_order_is_canonical() -> None:

    assert [s.value for s in TaskStatus] == [
        "pending",
        "in_progress",
        "on_hold",
        "completed",
        "blocked",
        "cancelled",
    ]


def test_enum_is_str_subclass_for_legacy_equality() -> None:

    assert TaskStatus.PENDING == "pending"
    assert TaskStatus.IN_PROGRESS == "in_progress"
    assert TaskStatus.COMPLETED.value == "completed"


def test_enum_supports_membership_via_string() -> None:

    assert "completed" in TASK_LIFECYCLE_FINISHED_STATUSES
    assert "cancelled" in TASK_LIFECYCLE_FINISHED_STATUSES
    assert "converted" not in TASK_LIFECYCLE_FINISHED_STATUSES
    assert "pending" not in TASK_LIFECYCLE_FINISHED_STATUSES
    assert "in_progress" not in TASK_LIFECYCLE_FINISHED_STATUSES




def test_every_member_has_metadata() -> None:
    assert set(TASK_STATUS_META.keys()) == set(TaskStatus)


def test_metadata_dataclass_is_frozen() -> None:
    meta = TASK_STATUS_META[TaskStatus.PENDING]
    assert isinstance(meta, TaskStatusMeta)
    try:
        meta.label = "Other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("TaskStatusMeta should be frozen")


def test_color_tokens_are_scss_variable_names_not_hex() -> None:

    for member, meta in TASK_STATUS_META.items():
        assert not meta.color_token.startswith("#"), (
            f"{member} has a hex literal color: {meta.color_token!r}; "
            "use an SCSS token name like 'color-status-complete' instead."
        )
        assert meta.color_token.startswith("color-"), (
            f"{member} color_token {meta.color_token!r} should start with 'color-'."
        )


def test_label_is_non_empty_human_readable() -> None:
    for member, meta in TASK_STATUS_META.items():
        assert meta.label, f"{member} has empty label"
        assert meta.label[0].isupper(), f"{member} label {meta.label!r} not capitalized"




def test_lifecycle_finished_set_matches_service_semantics() -> None:

    assert {s.value for s in TASK_LIFECYCLE_FINISHED_STATUSES} == {
        "completed",
        "cancelled",
    }


def test_valid_task_statuses_is_full_set() -> None:
    assert set(VALID_TASK_STATUSES) == set(TaskStatus)




def test_member_meta_property_returns_registered_metadata() -> None:
    assert TaskStatus.COMPLETED.meta is TASK_STATUS_META[TaskStatus.COMPLETED]


def test_is_lifecycle_finished_property() -> None:
    assert TaskStatus.COMPLETED.is_lifecycle_finished is True
    assert TaskStatus.CANCELLED.is_lifecycle_finished is True
    assert TaskStatus.PENDING.is_lifecycle_finished is False
    assert TaskStatus.IN_PROGRESS.is_lifecycle_finished is False
    assert TaskStatus.BLOCKED.is_lifecycle_finished is False




def test_blocked_is_decision_orange_and_cancelled_is_project_cancelled_red() -> None:
    from giljo_mcp.domain.project_status import PROJECT_STATUS_META, ProjectStatus

    assert TASK_STATUS_META[TaskStatus.BLOCKED].color_token == "color-status-warning"
    assert (
        TASK_STATUS_META[TaskStatus.CANCELLED].color_token == PROJECT_STATUS_META[ProjectStatus.CANCELLED].color_token
    )


def test_every_task_status_token_is_a_css_custom_property() -> None:
    from pathlib import Path

    scss = (Path(__file__).resolve().parents[3] / "frontend" / "src" / "styles" / "main.scss").read_text()
    for member, meta in TASK_STATUS_META.items():
        assert f"--{meta.color_token}:" in scss, (
            f"{member} uses {meta.color_token!r}, which main.scss does not define, so the badge falls back to grey."
        )
