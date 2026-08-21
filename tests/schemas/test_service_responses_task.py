# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
Tests for task-service Pydantic response models.

Split from test_service_responses.py — covers TaskListResponse, TaskUpdateResult,
TaskSummary, ConversionResult.

BE-9012d: the message-service models (SendMessageResult, BroadcastResult,
MessageListResult) and their tests were removed with the bus retirement —
those response shapes no longer have any producer.

Created: Handover 0731
"""

import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.service_responses import (
    ConversionResult,
    TaskListResponse,
    TaskSummary,
    TaskUpdateResult,
)


# ---------------------------------------------------------------------------
# Task Service Models
# ---------------------------------------------------------------------------


class TestTaskListResponse:
    """Tests for TaskListResponse model."""

    def test_creation_defaults(self):
        result = TaskListResponse()
        assert result.tasks == []
        assert result.count == 0

    def test_creation_with_tasks(self):
        tasks = [
            {"id": "t1", "title": "Task 1", "status": "pending"},
            {"id": "t2", "title": "Task 2", "status": "completed"},
        ]
        result = TaskListResponse(tasks=tasks, count=2)
        assert len(result.tasks) == 2
        assert result.count == 2
        assert result.tasks[0]["title"] == "Task 1"

    def test_tasks_default_factory_isolation(self):
        """Each instance should get its own list."""
        r1 = TaskListResponse()
        r2 = TaskListResponse()
        r1.tasks.append({"id": "t1"})
        assert len(r2.tasks) == 0

    def test_model_dump(self):
        result = TaskListResponse(tasks=[{"id": "t1"}], count=1)
        dumped = result.model_dump()
        assert dumped["count"] == 1
        assert len(dumped["tasks"]) == 1

    def test_from_attributes_config(self):
        assert TaskListResponse.model_config.get("from_attributes") is True


class TestTaskUpdateResult:
    """Tests for TaskUpdateResult model."""

    def test_creation_with_required_fields(self):
        result = TaskUpdateResult(task_id="task-123")
        assert result.task_id == "task-123"
        assert result.updated_fields == []

    def test_creation_with_updated_fields(self):
        result = TaskUpdateResult(
            task_id="task-456",
            updated_fields=["status", "priority", "description"],
        )
        assert len(result.updated_fields) == 3
        assert "status" in result.updated_fields

    def test_missing_task_id_raises(self):
        with pytest.raises(ValidationError):
            TaskUpdateResult()

    def test_updated_fields_default_factory_isolation(self):
        r1 = TaskUpdateResult(task_id="t1")
        r2 = TaskUpdateResult(task_id="t2")
        r1.updated_fields.append("title")
        assert "title" not in r2.updated_fields

    def test_model_dump(self):
        result = TaskUpdateResult(task_id="t1", updated_fields=["status"])
        dumped = result.model_dump()
        assert dumped["task_id"] == "t1"
        assert dumped["updated_fields"] == ["status"]

    def test_from_attributes_config(self):
        assert TaskUpdateResult.model_config.get("from_attributes") is True


class TestTaskSummary:
    """Tests for TaskSummary model."""

    def test_creation_defaults(self):
        summary = TaskSummary()
        assert summary.total == 0
        assert summary.by_status == {}
        assert summary.by_priority == {}
        assert summary.by_category == {}

    def test_creation_with_values(self):
        summary = TaskSummary(
            total=25,
            by_status={"pending": 10, "in_progress": 8, "completed": 7},
            by_priority={"high": 5, "medium": 15, "low": 5},
            by_category={"backend": 12, "frontend": 13},
        )
        assert summary.total == 25
        assert summary.by_status["pending"] == 10
        assert summary.by_priority["high"] == 5
        assert summary.by_category["backend"] == 12

    def test_dict_default_factory_isolation(self):
        """Each dict field should have its own instance."""
        s1 = TaskSummary()
        s2 = TaskSummary()
        s1.by_status["pending"] = 5
        assert "pending" not in s2.by_status

    def test_model_dump(self):
        summary = TaskSummary(total=3, by_status={"done": 3})
        dumped = summary.model_dump()
        assert dumped["total"] == 3
        assert dumped["by_status"] == {"done": 3}
        assert dumped["by_priority"] == {}

    def test_from_attributes_config(self):
        assert TaskSummary.model_config.get("from_attributes") is True


class TestConversionResult:
    """Tests for ConversionResult model."""

    def test_creation_with_required_fields(self):
        result = ConversionResult(
            task_id="task-1",
            project_id="proj-1",
            project_name="New Feature",
        )
        assert result.task_id == "task-1"
        assert result.project_id == "proj-1"
        assert result.project_name == "New Feature"

    def test_missing_task_id_raises(self):
        with pytest.raises(ValidationError):
            ConversionResult(project_id="p1", project_name="P")

    def test_missing_project_id_raises(self):
        with pytest.raises(ValidationError):
            ConversionResult(task_id="t1", project_name="P")

    def test_missing_project_name_raises(self):
        with pytest.raises(ValidationError):
            ConversionResult(task_id="t1", project_id="p1")

    def test_model_dump(self):
        result = ConversionResult(task_id="t", project_id="p", project_name="N")
        dumped = result.model_dump()
        # BE-9382: project_taxonomy_alias is optional -- the REST convert
        # endpoint builds its own response and never reads it, so a caller that
        # omits it still gets an explicit None rather than a missing key.
        # BE-9415: product_id/product_name join it on the same terms -- the
        # promotion binds to the task's own product and names it, and a caller
        # that omits them (the REST convert endpoint) still gets explicit Nones.
        assert dumped == {
            "task_id": "t",
            "project_id": "p",
            "project_name": "N",
            "project_taxonomy_alias": None,
            "product_id": None,
            "product_name": None,
        }

    def test_bound_product_round_trips(self):
        """BE-9415: the MCP promotion path echoes where the project landed."""
        result = ConversionResult(
            task_id="t",
            project_id="p",
            project_name="N",
            product_id="prod-1",
            product_name="Giljo HQ",
        )
        assert result.product_id == "prod-1"
        assert result.product_name == "Giljo HQ"

    def test_taxonomy_alias_round_trips(self):
        """BE-9382: the MCP promotion path reads the promoted project's serial back."""
        result = ConversionResult(task_id="t", project_id="p", project_name="N", project_taxonomy_alias="0017")
        assert result.project_taxonomy_alias == "0017"

    def test_from_attributes_config(self):
        assert ConversionResult.model_config.get("from_attributes") is True
