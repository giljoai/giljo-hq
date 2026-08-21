# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""
BE-9060 (item 3) / BE-9073 (item 2): regression guard for the task_service
mixin splits.

task_service.py (1552-line god-class) was first split into the task_service/
package, extracting the agent-facing MCP surface into
``_mcp_adapter_mixin.McpAdapterMixin`` (mirroring the project_service package
precedent). BE-9073 item 2 then split the remaining ~1134-line composed class
further into ``_query_mixin._TaskQueryMixin`` (read path),
``_mutation_mixin._TaskMutationMixin`` (core CRUD write path), and
``_lifecycle_mixin._TaskLifecycleMixin`` (status-change / conversion /
completion-notes -- split out of the mutation mixin so every file in the
package stays under the 800-line cap with no ``size_budgets.txt`` entry),
mirroring project_service's QueryMixin/MutationMixin. These tests lock the
split at the layer it changed: the public import surface, the mixin
composition, and the verbatim behavior of the pure row-projection helpers
that moved into the mcp-adapter mixin.

The full behavioral surface (create/update/list_for_mcp against a DB) is covered
by the existing service/integration suites (test_task_taxonomy_mcp_tools,
test_be6049c_tsk_namespace, test_task_tools_mcp_transport, ...). This file guards
the STRUCTURE so a future re-split cannot silently drop a method off the composed
class or break an importer.
"""

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
    """TaskService + _ALLOWED_TASK_UPDATE_FIELDS still import from the package path."""
    assert isinstance(_ALLOWED_TASK_UPDATE_FIELDS, frozenset)
    assert "title" in _ALLOWED_TASK_UPDATE_FIELDS
    # task_type_id stays excluded (TSK tag immutable — behavior unchanged by the split).
    assert "task_type_id" not in _ALLOWED_TASK_UPDATE_FIELDS


def test_taskservice_composes_the_mcp_adapter_mixin():
    assert issubclass(TaskService, McpAdapterMixin)


def test_taskservice_composes_the_query_and_mutation_mixins():
    """BE-9073 item 2: TaskService also composes the read/write/lifecycle mixins."""
    assert issubclass(TaskService, _TaskMutationMixin)
    assert issubclass(TaskService, _TaskLifecycleMixin)
    assert issubclass(TaskService, _TaskQueryMixin)


def test_allowed_update_fields_reexported_from_mutation_mixin():
    """_ALLOWED_TASK_UPDATE_FIELDS now lives in _mutation_mixin, re-exported
    at the package path for back-compat importers/tests."""
    assert _ALLOWED_TASK_UPDATE_FIELDS is _MUTATION_MIXIN_ALLOWED_FIELDS


def test_query_and_mutation_methods_resolve_on_composed_class():
    # Read-path methods that moved into _TaskQueryMixin.
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
    # Core CRUD write-path methods that moved into _TaskMutationMixin.
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
    # Status-change / conversion / completion-notes methods that moved into
    # _TaskLifecycleMixin (split out of _TaskMutationMixin to stay under 800 lines).
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
    """The package __name__ matches the old module, so the logger name is stable."""
    svc = TaskService.__module__
    assert svc == "giljo_mcp.services.task_service"


def test_facade_and_core_methods_all_resolve_on_composed_class():
    # Facade methods that moved into the mixin.
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
    # Core methods (now split across _TaskQueryMixin / _TaskMutationMixin,
    # BE-9073 item 2 -- still resolve unchanged on the composed class).
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
    """A minimal attribute bag matching what the row helpers read off a Task."""
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
        "due_date": None,
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
    # summary is the lean projection — no description column.
    assert "description" not in row


def test_full_row_truncates_description_at_memory_limit():
    row = TaskService._task_to_full_row(_stub_task(), memory_limit=10)
    assert row["description"] == "a" * 10 + "..."
    # no limit -> full description preserved.
    full = TaskService._task_to_full_row(_stub_task(), memory_limit=None)
    assert full["description"] == "a" * 50
    assert full["product_id"] == "prod-1"


# ---------------------------------------------------------------------------
# BE-9468: the read-layer fragment of the same package split.
#
# The bounds and projections for the agent-facing list live in a fourth module,
# ``_mcp_read_layer``, added rather than folded into ``_mcp_adapter_mixin`` because that
# file was at 654 lines against the 800-line cap. These tests guard it the way the rest
# of this file guards the split: the structure and the pure helpers, at the unit layer.
# The behavioral surface is covered end-to-end through the real MCP transport in
# tests/integration/test_be9468_list_tasks_read_layer.py.
# ---------------------------------------------------------------------------


def test_read_layer_bounds_are_ordered_and_sane():
    """The two row bounds must be usable together: a default you can actually raise."""
    assert 0 < read_layer.LIST_TASKS_LIMIT_DEFAULT < read_layer.LIST_TASKS_LIMIT_MAX
    # The char ceiling has to fit more than one row or the tool returns nothing.
    assert read_layer.LIST_TASKS_CHAR_CEILING > 10_000


def test_index_row_carries_no_embedded_type_block():
    """The lean row's whole point: the plain abbreviation, not a repeated constant object.

    The embedded block is byte-identical on every row (every task is TSK by contract) and
    carries a second UUID to say so. Here ``type`` is a string.
    """
    row = read_layer.task_to_index_row(_stub_task())
    assert row["type"] == "TSK"
    assert row["name"] == "Ship the thing"
    assert set(row) == {"task_id", "taxonomy_alias", "name", "status", "type", "due_date", "created_at"}
    assert read_layer.task_to_index_row(_stub_task(task_type=None))["type"] is None


def test_the_char_ceiling_drops_whole_rows_and_never_trims_one():
    """Rows, not fields. A row that survives is complete or it is not returned at all."""
    rows = [{"task_id": f"id-{i:03d}", "name": "n" * 200} for i in range(50)]
    kept, dropped = read_layer.fit_rows_to_char_ceiling(rows, envelope={"tasks": []}, ceiling=2_000)

    assert dropped > 0, "the fixture must actually overflow the ceiling or this proves nothing"
    assert len(kept) + dropped == len(rows)
    assert kept == rows[: len(kept)], "the cut falls on the TAIL -- the oldest rows"
    for row in kept:
        assert set(row) == {"task_id", "name"}, f"a surviving row must be whole, got {sorted(row)!r}"


def test_the_char_ceiling_actually_holds_as_a_postcondition():
    """The bound must HOLD, not approximately hold.

    The in-repo ``_response_ceiling`` helper writes its truncation metadata after its
    last size check and overshoots its own ceiling by exactly 64 chars while reporting
    success. A bound that does not hold is worse than no bound, because it reports a
    reassuring result. Asserted here as a property across a range of ceilings.
    """
    rows = [{"task_id": f"id-{i:03d}", "name": "n" * 200} for i in range(50)]
    for ceiling in (1_000, 2_000, 5_000, 12_000):
        envelope = {"tasks": [], "count": 0, "mode": "index"}
        kept, _dropped = read_layer.fit_rows_to_char_ceiling(rows, envelope=envelope, ceiling=ceiling)
        payload = dict(envelope, tasks=kept, count=len(kept))
        assert read_layer.wire_length(payload) <= ceiling, (
            f"the ceiling must hold: {read_layer.wire_length(payload)} chars over a {ceiling} ceiling"
        )


def test_a_ceiling_too_small_for_any_row_returns_none_rather_than_a_husk():
    """The degenerate case has to be a clean empty answer, not a partial row.

    Returning half a row would be the field-trimming failure mode arriving by the back
    door. Zero rows plus a truncation signal is an answer a caller can act on.
    """
    rows = [{"task_id": "id-1", "name": "n" * 500}]
    kept, dropped = read_layer.fit_rows_to_char_ceiling(rows, envelope={"tasks": []}, ceiling=10)
    assert kept == []
    assert dropped == 1


def test_the_truncation_block_reuses_the_shipped_vocabulary():
    """Extend the shipped shape; never invent a second one.

    A caller that learned to read a truncated project list must be able to read a
    truncated task list without learning anything new, so the keys are pinned here.
    """
    note = read_layer.truncation_note(
        reason="limit", ceiling=50, rows_fetched=50, dropped="the OLDEST-CREATED tasks", advice="narrow it"
    )
    assert set(note) == {"reason", "ceiling", "rows_fetched", "dropped", "advice"}


def test_apply_bounds_always_states_truncated_either_way():
    """``truncated`` is present on EVERY response, and the detail block only on a cut.

    Absence is indistinguishable from an older server, so the flag can never be omitted.
    """
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


# ---------------------------------------------------------------------------
# BE-9470: the filter-validator fragment of the same package split.
#
# resolve_list_mode / resolve_task_limit / the status+priority+task_type
# validators / resolve_task_type_id / resolve_active_product_for_list_tasks
# moved into a fifth module, ``_mcp_filter_validators``, split out of
# ``_mcp_read_layer`` when finding 4's mode-wins rewrite and finding 5's new
# task_type domain fix pushed that file to 838 lines against the 800-line cap.
# Behavioral coverage lives in tests/services/test_be9470_tasks_side.py; this
# guards the STRUCTURE the way the rest of this file guards every other split.
# ---------------------------------------------------------------------------


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
    # The mixin imports these names directly from the new module -- a stale
    # import back to _mcp_read_layer would be a silent re-break of the split.
    assert adapter.resolve_list_mode is validators.resolve_list_mode
    assert adapter.resolve_task_type_id is validators.resolve_task_type_id
