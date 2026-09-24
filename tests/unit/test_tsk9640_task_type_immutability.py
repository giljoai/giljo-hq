# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.services.task_type_immutability import (
    TASK_TYPE_FIELD,
    TASK_TYPE_IMMUTABLE_CONSTRAINT,
    TaskTypeImmutableError,
    require_no_task_type_change,
)


def test_a_different_type_is_refused_and_the_message_carries_the_remedy() -> None:
    with pytest.raises(TaskTypeImmutableError) as excinfo:
        require_no_task_type_change(current_type="TSK", requested_type="HND", task_id="abc-123")

    message = str(excinfo.value)
    assert "TSK" in message, "the refusal must name the type the task actually is"
    assert "HND" in message, "the refusal must name what was asked for"
    assert "create_task" in message, "the refusal must name the way to get what was asked for"
    assert "Nothing was changed" in message, message


def test_the_validator_is_silent_when_the_type_is_unchanged() -> None:
    require_no_task_type_change(current_type="TSK", requested_type="TSK", task_id="abc-123")
    require_no_task_type_change(current_type="HND", requested_type=" HND ", task_id="abc-123")


def test_an_omitted_type_is_not_a_request_to_change_one() -> None:
    require_no_task_type_change(current_type="TSK", requested_type="", task_id="abc-123")
    require_no_task_type_change(current_type="TSK", requested_type="   ", task_id="abc-123")


def test_the_comparison_is_case_sensitive() -> None:
    with pytest.raises(TaskTypeImmutableError):
        require_no_task_type_change(current_type="TSK", requested_type="tsk", task_id="abc-123")


def test_the_error_carries_the_boundary_rejection_coordinates() -> None:
    error = TaskTypeImmutableError(current_type="TSK", requested_type="HND", task_id="abc-123")
    assert error.field == TASK_TYPE_FIELD == "task_type"
    assert error.constraint == TASK_TYPE_IMMUTABLE_CONSTRAINT
    assert error.current_type == "TSK"
    assert error.requested_type == "HND"


def test_the_two_layers_produce_an_identical_rejection() -> None:
    from api.endpoints.mcp_tools._base import VALIDATION_ERROR, validation_rejection

    with pytest.raises(TaskTypeImmutableError) as excinfo:
        require_no_task_type_change(current_type="TSK", requested_type="HND", task_id="abc-123")
    error = excinfo.value

    boundary = validation_rejection(field=error.field, constraint=error.constraint, message=str(error))
    assert boundary["success"] is False
    assert boundary["error"] == VALIDATION_ERROR
    assert boundary["field"] == "task_type"
    assert boundary["message"] == str(error)
