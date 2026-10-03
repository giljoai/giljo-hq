# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


import pytest
from pydantic import ValidationError

from api.schemas.task import TaskCreate


def test_task_create_requires_product_id():
    with pytest.raises(ValidationError) as exc_info:
        TaskCreate(
            title="Test Task",
            description="Task without product_id",
            priority="medium",
        )

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("product_id",) for error in errors), "Error should be for product_id field"
    assert any(error["type"] == "missing" for error in errors), "Error type should be 'missing'"


def test_task_create_with_product_id_succeeds():
    task = TaskCreate(
        title="Test Task",
        description="Task with product_id",
        priority="high",
        product_id="test-product-123",
    )

    assert task.title == "Test Task"
    assert task.description == "Task with product_id"
    assert task.priority == "high"
    assert task.product_id == "test-product-123"
    assert task.status is None
    assert task.project_id is None


def test_task_create_product_id_is_string():
    task = TaskCreate(title="Test", product_id="uuid-string-here")
    assert isinstance(task.product_id, str)


def test_task_create_minimal_valid_data():
    task = TaskCreate(title="Minimal Task", product_id="product-abc")

    assert task.title == "Minimal Task"
    assert task.product_id == "product-abc"
    assert task.description is None
    assert task.status is None
    assert task.priority is None
    assert task.project_id is None


def test_task_create_with_all_fields():
    task = TaskCreate(
        title="Complete Task",
        description="Full task data",
        status="in_progress",
        priority="critical",
        task_type="BUG",
        product_id="product-xyz",
        project_id="project-123",
        parent_task_id="parent-456",
        estimated_effort=5.5,
        actual_effort=3.2,
    )

    assert task.title == "Complete Task"
    assert task.description == "Full task data"
    assert task.status == "in_progress"
    assert task.priority == "critical"
    assert task.task_type == "BUG"
    assert task.product_id == "product-xyz"
    assert task.project_id == "project-123"
    assert task.parent_task_id == "parent-456"
    assert task.estimated_effort == 5.5
    assert task.actual_effort == 3.2


def test_task_create_model_fields_metadata():
    fields = TaskCreate.model_fields

    assert "product_id" in fields, "product_id should be in model fields"
    product_id_field = fields["product_id"]
    assert product_id_field.is_required(), "product_id should be required"

    description = product_id_field.description
    assert description is not None, "product_id should have description"
    assert "Product ID" in description, "Description should say what the field is"
    assert "0433" not in description, "Description must not carry an internal id"




def test_task_create_invalid_status_rejected():
    with pytest.raises(ValidationError) as exc_info:
        TaskCreate(title="T", product_id="p", status="invalid_status")

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("status",) for error in errors)


def test_task_create_invalid_priority_rejected():
    with pytest.raises(ValidationError) as exc_info:
        TaskCreate(title="T", product_id="p", priority="urgent")

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("priority",) for error in errors)


def test_task_create_valid_status_values():
    valid_statuses = ["pending", "in_progress", "completed", "blocked", "cancelled"]
    for status in valid_statuses:
        task = TaskCreate(title="T", product_id="p", status=status)
        assert task.status == status


def test_task_create_valid_priority_values():
    valid_priorities = ["low", "medium", "high", "critical"]
    for priority in valid_priorities:
        task = TaskCreate(title="T", product_id="p", priority=priority)
        assert task.priority == priority


def test_status_update_invalid_status_rejected():
    from api.schemas.task import StatusUpdate

    with pytest.raises(ValidationError) as exc_info:
        StatusUpdate(status="active")

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("status",) for error in errors)


def test_task_update_invalid_status_rejected():
    from api.schemas.task import TaskUpdate

    with pytest.raises(ValidationError) as exc_info:
        TaskUpdate(status="broken")

    errors = exc_info.value.errors()
    assert any(error["loc"] == ("status",) for error in errors)
