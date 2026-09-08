# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Unit tests for ``giljo_mcp.domain.project_status``.

Asserts the canonical members exist (six original + BE-9157 superseded),
the metadata structure is well-formed, the derived sets match expectations,
and the ``str``-mixin behavior preserves the legacy comparison semantics that
the rest of the codebase still relies on.
"""

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


# ----------------------------------------------------------------------
# Enum membership
# ----------------------------------------------------------------------


def test_enum_has_exactly_canonical_members() -> None:
    """Canonical enum members; no STAGING, no ARCHIVED. BE-9157 added superseded;
    IMP-9258 added parked."""

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
    """Order matches the Postgres ENUM. ce_0008 declared the first six;
    BE-9157's ce_0078 appended ``superseded``; IMP-9258's ce_0083 appended
    ``parked`` LAST."""

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
    """``ProjectStatus.X == "x"`` must be True for legacy callers."""

    assert ProjectStatus.ACTIVE == "active"
    assert ProjectStatus.COMPLETED == "completed"
    # Confirm str-mixin equality is consistent: the enum value's
    # ``.value`` is itself a plain ``str``.
    assert ProjectStatus.ACTIVE.value == "active"


def test_enum_supports_membership_via_string() -> None:
    """``"completed" in IMMUTABLE_PROJECT_STATUSES`` works thanks to str mixin."""

    assert "completed" in IMMUTABLE_PROJECT_STATUSES
    assert "cancelled" in IMMUTABLE_PROJECT_STATUSES
    assert "active" not in IMMUTABLE_PROJECT_STATUSES


# ----------------------------------------------------------------------
# Metadata structure
# ----------------------------------------------------------------------


def test_every_member_has_metadata() -> None:
    """The drift guard at module import time also asserts this; double-check."""

    assert set(PROJECT_STATUS_META.keys()) == set(ProjectStatus)


def test_metadata_dataclass_is_frozen() -> None:
    """``ProjectStatusMeta`` is a frozen dataclass -- no accidental mutation."""

    meta = PROJECT_STATUS_META[ProjectStatus.ACTIVE]
    assert isinstance(meta, ProjectStatusMeta)
    try:
        meta.label = "Other"  # type: ignore[misc]
    except Exception:
        return
    raise AssertionError("ProjectStatusMeta should be frozen")


def test_color_tokens_are_scss_variable_names_not_hex() -> None:
    """Color tokens MUST be SCSS variable names -- no hex literals."""

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


# ----------------------------------------------------------------------
# Derived sets -- must match legacy frozensets verbatim
# ----------------------------------------------------------------------


def test_immutable_set_matches_legacy() -> None:
    """``IMMUTABLE_PROJECT_STATUSES``: completed + cancelled + (BE-9157) superseded.

    Superseded is immutable — an already-replaced project takes no further
    generic metadata edits (only the supersede transition itself reaches it).
    (IMP-9258) ``parked`` is deliberately NOT in this set -- it must stay a
    two-way door so the generic update_project() write path can unpark it.
    """

    assert {s.value for s in IMMUTABLE_PROJECT_STATUSES} == {"completed", "cancelled", "superseded"}
    assert "parked" not in IMMUTABLE_PROJECT_STATUSES


def test_lifecycle_finished_matches_legacy() -> None:
    """v1.2.1 BE-5037 set + (BE-9157) superseded: a closed, replaced state.

    (IMP-9258) ``parked`` is deliberately NOT in this set -- it is its own
    "hidden-but-not-finished" concept (own roadmap exclusion), not lumped in
    with the terminal states, so it stays visible in default project lists.
    """

    assert {s.value for s in LIFECYCLE_FINISHED_STATUSES} == {
        "completed",
        "cancelled",
        "terminated",
        "deleted",
        "superseded",
    }
    assert "parked" not in LIFECYCLE_FINISHED_STATUSES


def test_parked_status_properties() -> None:
    """(IMP-9258) ``parked`` is resumable (not finished, not immutable) and
    agent-settable via update_project."""

    assert ProjectStatus.PARKED.is_lifecycle_finished is False
    assert ProjectStatus.PARKED.is_immutable is False
    assert ProjectStatus.PARKED.is_user_mutable_via_mcp is True
    assert ProjectStatus.PARKED.label == "Parked"


def test_valid_update_set_matches_legacy() -> None:
    """``VALID_UPDATE_STATUSES`` == legacy MCP-tool whitelist + (IMP-9258) parked
    + (BE-9499b) superseded.

    Parked is agent-settable via update_project(status='parked') -- and
    unpark (status='active'|'inactive') reuses the same whitelist. Superseded
    is agent-settable via update_project(status='superseded',
    successor_project_id=...) -- the generic write's own successor-pointer
    validation (ProjectService.update_project /
    _lifecycle_redirects.require_supersede_successor) is what actually
    prevents a null-successor row, not this whitelist.
    """

    assert {s.value for s in VALID_UPDATE_STATUSES} == {
        "inactive",
        "active",
        "completed",
        "cancelled",
        "parked",
        "superseded",
    }


def test_valid_project_statuses_is_full_set() -> None:
    """``VALID_PROJECT_STATUSES`` == every enum member."""

    assert set(VALID_PROJECT_STATUSES) == set(ProjectStatus)


# ----------------------------------------------------------------------
# Convenience properties on the enum members
# ----------------------------------------------------------------------


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
