# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.handover_validation import (
    DOOR_MCP,
    DOOR_REST,
    HANDOVER_CONTENT_CONSTRAINT,
    HANDOVER_SHAPE_CONSTRAINT,
    REQUIRED_HANDOVER_HEADINGS,
)
from giljo_mcp.services.task_service._handover_guards import resolve_create_task_type


GOOD_HANDOVER = """Session ended at the rebase.

## Verify before trusting
- the branch is green -- check with: pytest tests/unit -q

## Waiting on the operator
- nothing

## Cannot testify
- the two-process concurrency behaviour; never observed it
"""

SKELETON = "\n\n".join(REQUIRED_HANDOVER_HEADINGS) + "\n"


def test_create_task_for_rest_accepts_a_task_type() -> None:
    from giljo_mcp.services.task_service import TaskService

    signature = inspect.signature(TaskService.create_task_for_rest)
    assert "task_type" in signature.parameters, "the REST create door cannot carry a task type"
    assert signature.parameters["task_type"].default is None, "omitting it must stay the TSK default"


def test_the_rest_door_resolves_a_handover() -> None:
    assert resolve_create_task_type("HND", GOOD_HANDOVER, door=DOOR_REST) == "HND"


def test_no_task_type_is_still_tsk() -> None:
    assert resolve_create_task_type(None, None, door=DOOR_REST) == "TSK"
    assert resolve_create_task_type("", "anything at all", door=DOOR_REST) == "TSK"


def test_the_rest_door_accepts_a_handover_of_any_shape() -> None:
    assert resolve_create_task_type("HND", SKELETON, door=DOOR_REST) == "HND"
    assert resolve_create_task_type("HND", "## Where I left off\nx", door=DOOR_REST) == "HND"
    assert resolve_create_task_type("HND", None, door=DOOR_REST) == "HND"


def test_a_handover_is_refused_on_the_mcp_door_when_the_shape_is_wrong() -> None:
    with pytest.raises(ValidationError) as caught:
        resolve_create_task_type("HND", SKELETON, door=DOOR_MCP)
    assert caught.value.context["constraint"] == HANDOVER_CONTENT_CONSTRAINT
    assert caught.value.context["field"] == "description"


def test_an_unknown_type_is_refused_by_name_before_any_heading_check() -> None:
    with pytest.raises(ValidationError) as caught:
        resolve_create_task_type("BE", "no headings here", door=DOOR_REST)
    assert caught.value.context["field"] == "task_type"
    assert "BE" in caught.value.message


def test_the_two_doors_refuse_a_bad_handover_identically() -> None:
    from api.endpoints.mcp_tools._task_tools import _handover_shape_rejection

    description = "## Verify before trusting\n- x\n\n## Waiting on the operator\n- nothing"

    boundary = _handover_shape_rejection(description)
    assert boundary is not None, "the MCP boundary accepted a handover with a missing heading"

    with pytest.raises(ValidationError) as caught:
        resolve_create_task_type("HND", description, door=DOOR_MCP)

    assert boundary["message"] == caught.value.message, (
        f"the two doors must say the same sentence:\n  mcp:  {boundary['message']!r}\n  rest: {caught.value.message!r}"
    )
    assert boundary["field"] == caught.value.context["field"]
    assert boundary["constraint"] == caught.value.context["constraint"]


def test_the_rest_endpoint_claims_exactly_the_two_argument_constraints() -> None:
    from api.endpoints.tasks import _ARGUMENT_CONSTRAINTS, _argument_rejection

    assert {HANDOVER_SHAPE_CONSTRAINT, HANDOVER_CONTENT_CONSTRAINT} == _ARGUMENT_CONSTRAINTS

    unrelated = ValidationError(message="Product is not active", context={"operation": "create_task_for_rest"})
    assert _argument_rejection(unrelated) is None, "an unrelated ValidationError must keep its own status"

    with pytest.raises(ValidationError) as caught:
        resolve_create_task_type("HND", SKELETON, door=DOOR_MCP)
    rejection = _argument_rejection(caught.value)
    assert rejection is not None and rejection.status_code == 422
    assert rejection.detail["error_code"] == "VALIDATION_ERROR"
    assert rejection.detail["message"] == caught.value.message
