# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from types import SimpleNamespace

from giljo_mcp.services.task_service import _ALLOWED_TASK_UPDATE_FIELDS, TaskService
from giljo_mcp.services.task_service import _mcp_read_layer as read_layer
from giljo_mcp.services.task_service._lifecycle_mixin import _TaskLifecycleMixin
from giljo_mcp.services.task_service._mcp_adapter_mixin import McpAdapterMixin
from giljo_mcp.services.task_service._mutation_mixin import (
    _ALLOWED_TASK_UPDATE_FIELDS as _MUTATION_MIXIN_ALLOWED_FIELDS,
)
from giljo_mcp.services.task_service._mutation_mixin import _TaskMutationMixin
from giljo_mcp.services.task_service._query_mixin import _TaskQueryMixin


def test_public_import_surface_preserved():
    assert isinstance(_ALLOWED_TASK_UPDATE_FIELDS, frozenset)
    assert "title" in _ALLOWED_TASK_UPDATE_FIELDS
    assert "task_type_id" not in _ALLOWED_TASK_UPDATE_FIELDS


def test_taskservice_composes_the_mcp_adapter_mixin():
    assert issubclass(TaskService, McpAdapterMixin)


def test_taskservice_composes_the_query_and_mutation_mixins():
    assert issubclass(TaskService, _TaskMutationMixin)
    assert issubclass(TaskService, _TaskLifecycleMixin)
    assert issubclass(TaskService, _TaskQueryMixin)


def test_allowed_update_fields_reexported_from_mutation_mixin():
    assert _ALLOWED_TASK_UPDATE_FIELDS is _MUTATION_MIXIN_ALLOWED_FIELDS


def test_query_and_mutation_methods_resolve_on_composed_class():
    for name in (
        "list_tasks",
        "_list_tasks_impl",
        "get_task",
        "_get_task_impl",
        "list_deleted_tasks",
        "get_summary",
    ):
        assert callable(getattr(TaskService, name)), name
        assert hasattr(_TaskQueryMixin, name), name
    for name in (
        "log_task",
        "_log_task_impl",
        "create_task",
        "create_task_for_rest",
        "update_task",
        "_update_task_impl",
        "delete_task",
        "_delete_task_impl",
        "restore_task",
        "_restore_task_impl",
        "purge_expired_deleted_tasks",
    ):
        assert callable(getattr(TaskService, name)), name
        assert hasattr(_TaskMutationMixin, name), name
    for name in (
        "convert_to_project",
        "change_status",
        "_change_status_impl",
        "_change_status_with_tenant",
        "append_completion_notes",
        "_append_completion_notes",
    ):
        assert callable(getattr(TaskService, name)), name
        assert hasattr(_TaskLifecycleMixin, name), name


def test_logger_name_unchanged_after_package_conversion():
    svc = TaskService.__module__
    assert svc == "giljo_mcp.services.task_service"


def test_facade_and_core_methods_all_resolve_on_composed_class():
    for name in (
        "create_task_for_mcp",
        "update_task_for_mcp",
        "list_tasks_for_mcp",
        "_list_tasks_for_mcp_impl",
        "_task_type_block",
        "_task_to_summary_row",
        "_task_to_full_row",
    ):
        assert callable(getattr(TaskService, name)), name
    for name in (
        "log_task",
        "create_task",
        "update_task",
        "get_task",
        "delete_task",
        "restore_task",
        "append_completion_notes",
        "_append_completion_notes",
        "_change_status_with_tenant",
    ):
        assert callable(getattr(TaskService, name)), name


def _stub_task(**overrides):
    base = {
        "id": "task-123",
        "title": "Ship the thing",
        "status": "in_progress",
        "priority": "high",
        "task_type": SimpleNamespace(id="tt-1", abbreviation="TSK", label="Task", color="#abc"),
        "taxonomy_alias": "TSK-0042",
        "series_number": 42,
        "subseries": None,
        "hidden": False,
        "created_at": None,
        "description": "a" * 50,
        "task_type_id": "tt-1",
        "product_id": "prod-1",
        "project_id": None,
        "parent_task_id": None,
        "estimated_effort": None,
        "actual_effort": None,
        "started_at": None,
        "completed_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_task_type_block_shape():
    block = TaskService._task_type_block(_stub_task())
    assert block == {"id": "tt-1", "abbreviation": "TSK", "label": "Task", "color": "#abc"}
    assert TaskService._task_type_block(_stub_task(task_type=None)) is None


def test_summary_row_shape():
    row = TaskService._task_to_summary_row(_stub_task())
    assert row["task_id"] == "task-123"
    assert row["taxonomy_alias"] == "TSK-0042"
    assert row["task_type"]["abbreviation"] == "TSK"
    assert row["hidden"] is False
    assert "description" not in row


def test_full_row_truncates_description_at_memory_limit():
    row = TaskService._task_to_full_row(_stub_task(), memory_limit=10)
    assert row["description"] == "a" * 10 + "..."
    full = TaskService._task_to_full_row(_stub_task(), memory_limit=None)
    assert full["description"] == "a" * 50
    assert full["product_id"] == "prod-1"




def test_read_layer_bounds_are_ordered_and_sane():
    assert 0 < read_layer.LIST_TASKS_LIMIT_DEFAULT < read_layer.LIST_TASKS_LIMIT_MAX
    assert read_layer.LIST_TASKS_CHAR_CEILING > 10_000


def test_index_row_carries_no_embedded_type_block():
    row = read_layer.task_to_index_row(_stub_task())
    assert row["type"] == "TSK"
    assert row["name"] == "Ship the thing"
    assert set(row) == {"task_id", "taxonomy_alias", "name", "status", "type", "created_at"}
    assert read_layer.task_to_index_row(_stub_task(task_type=None))["type"] is None


def test_the_char_ceiling_drops_whole_rows_and_never_trims_one():
    rows = [{"task_id": f"id-{i:03d}", "name": "n" * 200} for i in range(50)]
    kept, dropped = read_layer.fit_rows_to_char_ceiling(rows, envelope={"tasks": []}, ceiling=2_000)

    assert dropped > 0, "the fixture must actually overflow the ceiling or this proves nothing"
    assert len(kept) + dropped == len(rows)
    assert kept == rows[: len(kept)], "the cut falls on the TAIL -- the oldest rows"
    for row in kept:
        assert set(row) == {"task_id", "name"}, f"a surviving row must be whole, got {sorted(row)!r}"


def test_the_char_ceiling_actually_holds_as_a_postcondition():
    rows = [{"task_id": f"id-{i:03d}", "name": "n" * 200} for i in range(50)]
    for ceiling in (1_000, 2_000, 5_000, 12_000):
        envelope = {"tasks": [], "count": 0, "mode": "index"}
        kept, _dropped = read_layer.fit_rows_to_char_ceiling(rows, envelope=envelope, ceiling=ceiling)
        payload = dict(envelope, tasks=kept, count=len(kept))
        assert read_layer.wire_length(payload) <= ceiling, (
            f"the ceiling must hold: {read_layer.wire_length(payload)} chars over a {ceiling} ceiling"
        )


def test_a_ceiling_too_small_for_any_row_returns_none_rather_than_a_husk():
    rows = [{"task_id": "id-1", "name": "n" * 500}]
    kept, dropped = read_layer.fit_rows_to_char_ceiling(rows, envelope={"tasks": []}, ceiling=10)
    assert kept == []
    assert dropped == 1


def test_the_truncation_block_reuses_the_shipped_vocabulary():
    note = read_layer.truncation_note(
        reason="limit", ceiling=50, rows_fetched=50, dropped="the OLDEST-CREATED tasks", advice="narrow it"
    )
    assert set(note) == {"reason", "ceiling", "rows_fetched", "dropped", "advice"}


def test_apply_bounds_always_states_truncated_either_way():
    small = read_layer.apply_bounds(
        {"tasks": [{"task_id": "a"}], "count": 1}, [{"task_id": "a"}], limit_cut=False, effective_limit=50
    )
    assert small["truncated"] is False
    assert "truncation" not in small

    cut = read_layer.apply_bounds(
        {"tasks": [{"task_id": "a"}], "count": 1}, [{"task_id": "a"}], limit_cut=True, effective_limit=1
    )
    assert cut["truncated"] is True
    assert cut["truncation"]["reason"] == "limit"




def test_filter_validators_module_exists_and_is_imported_by_the_mixin():
    from giljo_mcp.services.task_service import _mcp_adapter_mixin as adapter
    from giljo_mcp.services.task_service import _mcp_filter_validators as validators

    for name in (
        "resolve_list_mode",
        "resolve_task_limit",
        "validate_task_status_filter",
        "validate_task_type_filter",
        "normalize_task_priority_filter",
        "resolve_task_type_id",
        "resolve_active_product_for_list_tasks",
    ):
        assert callable(getattr(validators, name)), name
    assert adapter.resolve_list_mode is validators.resolve_list_mode
    assert adapter.resolve_task_type_id is validators.resolve_task_type_id
