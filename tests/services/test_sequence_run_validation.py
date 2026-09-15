# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.sequence_run_validation import (
    MAX_CHAIN_MISSION_CHARS,
    validate_create_fields,
    validate_update_fields,
)


def _valid_create_kwargs() -> dict:
    return {
        "project_ids": ["p1", "p2"],
        "execution_mode": "multi_terminal",
        "status": "pending",
        "review_policy": "per_card",
        "project_statuses": {"p1": "pending", "p2": "pending"},
    }


def test_validate_create_fields_accepts_valid() -> None:
    validate_create_fields(**_valid_create_kwargs())


def test_validate_create_fields_rejects_empty_project_ids() -> None:
    kwargs = _valid_create_kwargs()
    kwargs["project_ids"] = []
    with pytest.raises(ValidationError):
        validate_create_fields(**kwargs)


def test_validate_create_fields_rejects_bad_execution_mode() -> None:
    kwargs = _valid_create_kwargs()
    kwargs["execution_mode"] = "not_a_mode"
    with pytest.raises(ValidationError):
        validate_create_fields(**kwargs)


def test_validate_create_fields_rejects_bad_project_status() -> None:
    kwargs = _valid_create_kwargs()
    kwargs["project_statuses"] = {"p1": "bogus"}
    with pytest.raises(ValidationError):
        validate_create_fields(**kwargs)


def test_validate_update_fields_passes_through_and_normalizes() -> None:
    resolved_order, project_statuses = validate_update_fields(
        status="running",
        review_policy=None,
        current_index=1,
        execution_mode=None,
        chain_mission="a short cross-project plan",
        resolved_order=["p1", "p2"],
        project_statuses={"p1": "completed"},
    )
    assert resolved_order == ["p1", "p2"]
    assert project_statuses == {"p1": "completed"}


def test_validate_update_fields_rejects_over_cap_chain_mission() -> None:
    with pytest.raises(ValidationError):
        validate_update_fields(
            status=None,
            review_policy=None,
            current_index=None,
            execution_mode=None,
            chain_mission="x" * (MAX_CHAIN_MISSION_CHARS + 1),
            resolved_order=None,
            project_statuses=None,
        )


def test_validate_update_fields_rejects_negative_index() -> None:
    with pytest.raises(ValidationError):
        validate_update_fields(
            status=None,
            review_policy=None,
            current_index=-1,
            execution_mode=None,
            chain_mission=None,
            resolved_order=None,
            project_statuses=None,
        )


def test_validate_update_fields_all_none_is_noop() -> None:
    resolved_order, project_statuses = validate_update_fields(
        status=None,
        review_policy=None,
        current_index=None,
        execution_mode=None,
        chain_mission=None,
        resolved_order=None,
        project_statuses=None,
    )
    assert resolved_order is None
    assert project_statuses is None
