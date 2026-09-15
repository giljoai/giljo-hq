# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.text_field_validation import require_non_blank


@pytest.mark.parametrize("value", [None, "", "   ", "\t\n"])
def test_blank_values_are_refused(value):
    with pytest.raises(ValidationError) as exc_info:
        require_non_blank(value, field="title", operation="create_task", entity="Task")
    err = exc_info.value
    assert "Task title" in err.message
    assert err.context["field"] == "title"
    assert err.context["operation"] == "create_task"


def test_non_blank_value_is_returned_unchanged():
    assert require_non_blank(" real ", field="name", operation="create_project", entity="Project") == " real "


def test_max_length_is_enforced_when_given():
    with pytest.raises(ValidationError) as exc_info:
        require_non_blank("x" * 256, field="name", operation="create_project", entity="Project", max_length=255)
    assert "255" in exc_info.value.message
    assert require_non_blank("x" * 255, field="name", operation="create_project", entity="Project", max_length=255)


def test_extra_context_is_carried():
    with pytest.raises(ValidationError) as exc_info:
        require_non_blank("", field="title", operation="update_task", entity="Task", task_id="t-1")
    assert exc_info.value.context["task_id"] == "t-1"
