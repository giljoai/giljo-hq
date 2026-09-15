# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from giljo_mcp.domain.project_status import (
    IMMUTABLE_PROJECT_STATUSES,
    LIFECYCLE_FINISHED_STATUSES,
    PROJECT_STATUS_META,
    VALID_PROJECT_STATUSES,
    VALID_UPDATE_STATUSES,
    ProjectStatus,
    ProjectStatusMeta,
)




def test_enum_has_exactly_canonical_members() -> None:

    assert {s.value for s in ProjectStatus} == {
        "inactive",
        "active",
        "completed",
        "cancelled",
        "terminated",
        "deleted",
        "superseded",
        "parked",
    }


def test_enum_declaration_order_matches_postgres_enum() -> None:

    assert [s.value for s in ProjectStatus] == [
        "inactive",
        "active",
        "completed",
        "cancelled",
        "terminated",
        "deleted",
        "superseded",
        "parked",
    ]


def test_enum_is_str_subclass_for_legacy_equality() -> None:

    assert ProjectStatus.ACTIVE == "active"
    assert ProjectStatus.COMPLETED == "completed"
    assert ProjectStatus.ACTIVE.value == "active"


def test_enum_supports_membership_via_string() -> None:

    assert "completed" in IMMUTABLE_PROJECT_STATUSES
    assert "cancelled" in IMMUTABLE_PROJECT_STATUSES
    assert "active" not in IMMUTABLE_PROJECT_STATUSES




def test_every_member_has_metadata() -> None:

    assert set(PROJECT_STATUS_META.keys()) == set(ProjectStatus)


def test_metadata_dataclass_is_frozen() -> None:

    meta = PROJECT_STATUS_META[ProjectStatus.ACTIVE]
    assert isinstance(meta, ProjectStatusMeta)
    try:
        meta.label = "Other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ProjectStatusMeta should be frozen")


def test_color_tokens_are_scss_variable_names_not_hex() -> None:

    for member, meta in PROJECT_STATUS_META.items():
        assert not meta.color_token.startswith("#"), (
            f"{member} has a hex literal color: {meta.color_token!r}; "
            "use an SCSS token name like 'color-status-complete' instead."
        )
        assert meta.color_token.startswith("color-"), (
            f"{member} color_token {meta.color_token!r} should start with 'color-'."
        )


def test_label_is_non_empty_human_readable() -> None:
    for member, meta in PROJECT_STATUS_META.items():
        assert meta.label, f"{member} has empty label"
        assert meta.label[0].isupper(), f"{member} label {meta.label!r} not capitalized"




def test_immutable_set_matches_legacy() -> None:

    assert {s.value for s in IMMUTABLE_PROJECT_STATUSES} == {"completed", "cancelled", "superseded"}
    assert "parked" not in IMMUTABLE_PROJECT_STATUSES


def test_lifecycle_finished_matches_legacy() -> None:

    assert {s.value for s in LIFECYCLE_FINISHED_STATUSES} == {
        "completed",
        "cancelled",
        "terminated",
        "deleted",
        "superseded",
    }
    assert "parked" not in LIFECYCLE_FINISHED_STATUSES


def test_parked_status_properties() -> None:

    assert ProjectStatus.PARKED.is_lifecycle_finished is False
    assert ProjectStatus.PARKED.is_immutable is False
    assert ProjectStatus.PARKED.is_user_mutable_via_mcp is True
    assert ProjectStatus.PARKED.label == "Parked"


def test_valid_update_set_matches_legacy() -> None:

    assert {s.value for s in VALID_UPDATE_STATUSES} == {
        "inactive",
        "active",
        "completed",
        "cancelled",
        "parked",
        "superseded",
    }


def test_valid_project_statuses_is_full_set() -> None:

    assert set(VALID_PROJECT_STATUSES) == set(ProjectStatus)




def test_member_meta_property_returns_registered_metadata() -> None:
    assert ProjectStatus.COMPLETED.meta is PROJECT_STATUS_META[ProjectStatus.COMPLETED]


def test_is_lifecycle_finished_property() -> None:
    assert ProjectStatus.COMPLETED.is_lifecycle_finished is True
    assert ProjectStatus.ACTIVE.is_lifecycle_finished is False


def test_is_immutable_property() -> None:
    assert ProjectStatus.COMPLETED.is_immutable is True
    assert ProjectStatus.TERMINATED.is_immutable is False


def test_is_user_mutable_via_mcp_property() -> None:
    assert ProjectStatus.ACTIVE.is_user_mutable_via_mcp is True
    assert ProjectStatus.TERMINATED.is_user_mutable_via_mcp is False
    assert ProjectStatus.DELETED.is_user_mutable_via_mcp is False
