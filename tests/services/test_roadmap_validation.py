# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.


import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.roadmaps import (
    MAX_BLOCKED_REASON_LEN,
    MAX_ROADMAP_SORT_ORDER,
    VALID_ROADMAP_COMPLEXITIES,
    VALID_ROADMAP_ITEM_TYPES,
    VALID_ROADMAP_RISKS,
)
from giljo_mcp.services.roadmap_validation import (
    validate_blocked,
    validate_items,
    validate_remove,
    validate_reorder,
    validate_sort_order,
)


VALID_RISK = next(iter(VALID_ROADMAP_RISKS))
VALID_COMPLEXITY = next(iter(VALID_ROADMAP_COMPLEXITIES))




def test_validate_items_empty_list():
    assert validate_items([]) == []


def test_validate_items_normalizes_project_item():
    out = validate_items(
        [
            {
                "item_type": "project",
                "project_id": 123,
                "sort_order": 3,
                "risk": VALID_RISK,
                "complexity": VALID_COMPLEXITY,
            }
        ]
    )
    assert out == [
        {
            "item_type": "project",
            "project_id": "123",
            "task_id": None,
            "sort_order": 3,
            "risk": VALID_RISK,
            "complexity": VALID_COMPLEXITY,
            "blocked": False,
            "blocked_reason": None,
        }
    ]


def test_validate_items_normalizes_task_item_and_clears_project_id():
    out = validate_items([{"item_type": "task", "task_id": "t1", "project_id": "ignored"}])
    assert out[0]["task_id"] == "t1"
    assert out[0]["project_id"] is None


def test_validate_items_rejects_non_list():
    with pytest.raises(ValidationError):
        validate_items({"item_type": "project"})


def test_validate_items_rejects_non_dict_element():
    with pytest.raises(ValidationError):
        validate_items(["not-an-object"])


def test_validate_items_rejects_bad_item_type():
    bad = "milestone"
    assert bad not in VALID_ROADMAP_ITEM_TYPES
    with pytest.raises(ValidationError):
        validate_items([{"item_type": bad, "project_id": "p1"}])


def test_validate_items_project_requires_project_id():
    with pytest.raises(ValidationError):
        validate_items([{"item_type": "project"}])


def test_validate_items_task_requires_task_id():
    with pytest.raises(ValidationError):
        validate_items([{"item_type": "task"}])


def test_validate_items_rejects_bad_risk():
    with pytest.raises(ValidationError):
        validate_items([{"item_type": "project", "project_id": "p1", "risk": "nope"}])


def test_validate_items_rejects_bad_complexity():
    with pytest.raises(ValidationError):
        validate_items([{"item_type": "project", "project_id": "p1", "complexity": "nope"}])


def test_validate_items_blocked_true_keeps_reason():
    out = validate_items([{"item_type": "project", "project_id": "p1", "blocked": True, "blocked_reason": " waiting "}])
    assert out[0]["blocked"] is True
    assert out[0]["blocked_reason"] == "waiting"


def test_validate_items_blocked_false_drops_reason():
    out = validate_items([{"item_type": "project", "project_id": "p1", "blocked": False, "blocked_reason": "stale"}])
    assert out[0]["blocked"] is False
    assert out[0]["blocked_reason"] is None




@pytest.mark.parametrize("value", [0, 1, MAX_ROADMAP_SORT_ORDER])
def test_validate_sort_order_accepts_in_range(value):
    assert validate_sort_order(value, 0) == value


@pytest.mark.parametrize("value", [-1, MAX_ROADMAP_SORT_ORDER + 1])
def test_validate_sort_order_rejects_out_of_range(value):
    with pytest.raises(ValidationError):
        validate_sort_order(value, 0)


@pytest.mark.parametrize("value", [True, 1.5, "3", None])
def test_validate_sort_order_rejects_non_int(value):
    with pytest.raises(ValidationError):
        validate_sort_order(value, 0)




def test_validate_blocked_defaults_false():
    assert validate_blocked(None, None, 0) == (False, None)


def test_validate_blocked_rejects_non_bool():
    with pytest.raises(ValidationError):
        validate_blocked("yes", None, 0)


def test_validate_blocked_rejects_non_string_reason():
    with pytest.raises(ValidationError):
        validate_blocked(True, 123, 0)


def test_validate_blocked_rejects_overlong_reason():
    with pytest.raises(ValidationError):
        validate_blocked(True, "x" * (MAX_BLOCKED_REASON_LEN + 1), 0)




def test_validate_reorder_normalizes():
    assert validate_reorder([{"id": 7, "sort_order": 2}]) == [{"id": "7", "sort_order": 2}]


def test_validate_reorder_rejects_non_list():
    with pytest.raises(ValidationError):
        validate_reorder({"id": "x"})


def test_validate_reorder_requires_id():
    with pytest.raises(ValidationError):
        validate_reorder([{"sort_order": 1}])


def test_validate_reorder_rejects_bad_sort_order():
    with pytest.raises(ValidationError):
        validate_reorder([{"id": "x", "sort_order": -5}])




def test_validate_remove_none_is_empty():
    assert validate_remove(None) == []


def test_validate_remove_normalizes_project_ref():
    out = validate_remove([{"item_type": "project", "project_id": 9}])
    assert out == [{"item_type": "project", "project_id": "9", "task_id": None}]


def test_validate_remove_normalizes_task_ref():
    out = validate_remove([{"item_type": "task", "task_id": "t9"}])
    assert out == [{"item_type": "task", "project_id": None, "task_id": "t9"}]


def test_validate_remove_rejects_non_list():
    with pytest.raises(ValidationError):
        validate_remove({"item_type": "project"})


def test_validate_remove_rejects_bad_item_type():
    with pytest.raises(ValidationError):
        validate_remove([{"item_type": "nope", "project_id": "p1"}])


def test_validate_remove_project_requires_project_id():
    with pytest.raises(ValidationError):
        validate_remove([{"item_type": "project"}])


def test_validate_remove_task_requires_task_id():
    with pytest.raises(ValidationError):
        validate_remove([{"item_type": "task"}])
