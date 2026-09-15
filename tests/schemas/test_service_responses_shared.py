# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from giljo_mcp.schemas.service_responses import (
    AuthResult,
    DeleteResult,
    OperationResult,
    PaginatedResult,
    ProductStatistics,
    SpawnResult,
    TaskSummary,
)




class TestDeleteResult:

    def test_creation_defaults(self):
        result = DeleteResult()
        assert result.deleted is True
        assert result.deleted_at is None

    def test_creation_with_timestamp(self):
        ts = datetime(2026, 1, 15, 12, 0, 0, tzinfo=UTC)
        result = DeleteResult(deleted=True, deleted_at=ts)
        assert result.deleted is True
        assert result.deleted_at == ts

    def test_model_dump(self):
        result = DeleteResult()
        dumped = result.model_dump()
        assert isinstance(dumped, dict)
        assert dumped["deleted"] is True
        assert dumped["deleted_at"] is None

    def test_from_attributes_config(self):
        assert DeleteResult.model_config.get("from_attributes") is True


class TestOperationResult:

    def test_creation_with_message(self):
        result = OperationResult(message="Product activated successfully")
        assert result.message == "Product activated successfully"

    def test_missing_message_raises(self):
        with pytest.raises(ValidationError):
            OperationResult()

    def test_model_dump(self):
        result = OperationResult(message="Done")
        dumped = result.model_dump()
        assert dumped == {"message": "Done"}

    def test_from_attributes_config(self):
        assert OperationResult.model_config.get("from_attributes") is True


class TestPaginatedResult:

    def test_creation_with_string_items(self):
        result = PaginatedResult[str](items=["a", "b", "c"], total=3)
        assert result.items == ["a", "b", "c"]
        assert result.total == 3
        assert result.page == 1
        assert result.page_size == 50

    def test_creation_with_int_items(self):
        result = PaginatedResult[int](items=[1, 2], total=100, page=2, page_size=25)
        assert result.items == [1, 2]
        assert result.total == 100
        assert result.page == 2
        assert result.page_size == 25

    def test_creation_with_dict_items(self):
        items = [{"id": "1", "name": "Product A"}, {"id": "2", "name": "Product B"}]
        result = PaginatedResult[dict](items=items, total=2)
        assert len(result.items) == 2
        assert result.items[0]["name"] == "Product A"

    def test_empty_items(self):
        result = PaginatedResult[str](items=[], total=0)
        assert result.items == []
        assert result.total == 0

    def test_missing_total_raises(self):
        with pytest.raises(ValidationError):
            PaginatedResult[str](items=["a"])

    def test_missing_items_raises(self):
        with pytest.raises(ValidationError):
            PaginatedResult[str](total=5)

    def test_model_dump(self):
        result = PaginatedResult[str](items=["x"], total=1, page=3, page_size=10)
        dumped = result.model_dump()
        assert dumped["items"] == ["x"]
        assert dumped["total"] == 1
        assert dumped["page"] == 3
        assert dumped["page_size"] == 10

    def test_from_attributes_config(self):
        assert PaginatedResult.model_config.get("from_attributes") is True




class TestModelJsonSerialization:

    def test_delete_result_with_datetime_json(self):
        ts = datetime(2026, 2, 1, 10, 30, 0, tzinfo=UTC)
        result = DeleteResult(deleted_at=ts)
        json_str = result.model_dump_json()
        assert "2026" in json_str

    def test_paginated_result_json(self):
        result = PaginatedResult[str](items=["a", "b"], total=2)
        json_str = result.model_dump_json()
        assert '"items"' in json_str
        assert '"total"' in json_str

    def test_task_summary_nested_dicts_json(self):
        summary = TaskSummary(
            total=10,
            by_status={"pending": 5, "completed": 5},
        )
        json_str = summary.model_dump_json()
        assert '"pending"' in json_str


class TestModelFromDict:

    def test_spawn_result_from_dict(self):
        data = {"job_id": "j1", "agent_id": "a1", "agent_prompt": "prompt"}
        result = SpawnResult(**data)
        assert result.job_id == "j1"

    def test_auth_result_from_dict(self):
        data = {
            "user_id": "u1",
            "username": "admin",
            "token": "jwt",
            "tenant_key": "tk",
            "role": "admin",
        }
        result = AuthResult(**data)
        assert result.role == "admin"

    def test_product_statistics_from_partial_dict(self):
        data = {"product_id": "p1", "name": "Test", "is_active": True, "project_count": 5}
        stats = ProductStatistics(**data)
        assert stats.project_count == 5
        assert stats.task_count == 0
