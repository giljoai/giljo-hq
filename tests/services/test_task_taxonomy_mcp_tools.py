# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""Tenant-isolation + happy-path tests for the Phase B/C/D MCP task tools.

Covers:
- ``TaskService.create_task_for_mcp`` (Phase B): task_type validation against
  TaxonomyService; rejection payload includes valid_types.
- ``TaskService.update_task_for_mcp`` (Phase C): status transitions, enum
  validation, task_type rebind, completion via status=completed, tenant scoping,
  TaskService-routed write.
- ``TaskService.list_tasks_for_mcp`` (Phase D): summary/full mode shapes,
  filters, tenant scoping.

Real DB; no mocks. Uses the two_tenant_service_setup fixture from
tests/services/conftest.py.
"""

from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.taxonomy_service import TaxonomyService


pytestmark = pytest.mark.asyncio


async def _seed_taxonomy_for(db_session, tenant_key: str, db_manager) -> None:
    """Seed BE/FE/INF rows for a tenant using TaxonomyService (test-scoped session).

    Idempotent: skips abbreviations that already exist. Commits via the test's
    db_session so rows are visible to the new sessions that
    ``create_task_for_mcp`` opens via ``db_manager.get_session_async()``.
    """
    service = TaxonomyService(db_manager=db_manager, session=db_session)
    existing = {row.abbreviation for row in await service.list_types(tenant_key)}
    for i, (abbr, label) in enumerate([("BE", "Backend"), ("FE", "Frontend"), ("INF", "Infrastructure")]):
        if abbr in existing:
            continue
        await service.create_type(
            tenant_key=tenant_key,
            abbreviation=abbr,
            label=label,
            sort_order=i,
        )
    await db_session.commit()


# ---------------------------------------------------------------------------
# Phase B: create_task_for_mcp + task_type validation
# ---------------------------------------------------------------------------


async def test_create_task_for_mcp_forces_tsk_tag(db_session, two_tenant_service_setup):
    """BE-6049c: tasks are TSK-only. A supplied task_type is ignored."""
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="Investigate flaky test",
        description="Repro and fix the websocket flake",
        priority="high",
        task_type="BE",  # ignored — every task is forced onto TSK
        tenant_key=tenant_a,
        db_manager=db_manager,
    )

    assert response["success"] is True
    assert response["task_id"]
    assert response["task_type"] == "TSK"
    assert response["taxonomy_alias"].startswith("TSK-")
    assert "valid_types" not in response


async def test_create_task_for_mcp_unknown_task_type_is_ignored_not_rejected(db_session, two_tenant_service_setup):
    """BE-6049c: task_type is no longer validated/selectable — garbage is ignored, TSK forced."""
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="garbage type",
        description="unknown task_type no longer errors",
        task_type="MADEUP",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )

    assert response["success"] is True
    assert response["task_type"] == "TSK"


async def test_create_task_for_mcp_omitted_task_type_still_forces_tsk(db_session, two_tenant_service_setup):
    """BE-6049c: omitting task_type still yields a TSK task; no valid_types hint anymore."""
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="No type provided",
        description="UI hint flow",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )

    assert response["success"] is True
    assert response["task_type"] == "TSK"
    assert "valid_types" not in response


# ---------------------------------------------------------------------------
# Phase C: update_task_for_mcp (status transitions, completion via status=completed)
# ---------------------------------------------------------------------------


async def _create_seed_task(db_session, two_tenant_service_setup) -> str:
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]
    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="seed task",
        description="for status updates",
        task_type="BE",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    return response["task_id"]


async def test_update_task_status_field_transitions_to_in_progress(db_session, two_tenant_service_setup):
    """Status flows through update_task (no dedicated update_task_status tool)."""
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        status="in_progress",
        tenant_key=tenant_a,
    )

    assert response["task_id"] == task_id
    assert "status" in response["updated_fields"]


async def test_update_task_blocks_cross_tenant_task(db_session, two_tenant_service_setup):
    """Tenant A may not update a Tenant B task — 404, not 200."""
    from giljo_mcp.exceptions import ResourceNotFoundError
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tenant import TenantManager

    tenant_a = two_tenant_service_setup["tenant_a"]
    tenant_b = two_tenant_service_setup["tenant_b"]
    db_manager = two_tenant_service_setup["db_manager"]
    await _seed_taxonomy_for(db_session, tenant_b, db_manager)

    task_service_b = TaskService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
    )
    response = await task_service_b.create_task_for_mcp(
        title="tenant b task",
        description="x",
        task_type="BE",
        tenant_key=tenant_b,
        db_manager=db_manager,
    )
    b_task_id = response["task_id"]

    task_service_a = two_tenant_service_setup["task_service_a"]
    with pytest.raises(ResourceNotFoundError):
        await task_service_a.update_task_for_mcp(
            task_id=b_task_id,
            status="in_progress",
            tenant_key=tenant_a,
        )


# ---------------------------------------------------------------------------
# Phase C addition: update_task_for_mcp (full-field update + task_type rebind)
# ---------------------------------------------------------------------------


async def test_update_task_changes_title_and_priority(db_session, two_tenant_service_setup):
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        title="Renamed",
        priority="critical",
    )

    assert response["task_id"] == task_id
    assert "title" in response["updated_fields"]
    assert "priority" in response["updated_fields"]


async def test_update_task_task_type_is_immutable(db_session, two_tenant_service_setup):
    """BE-6049c: TSK is immutable. Passing a known task_type is a no-op —
    ``task_type_id`` is excluded from the update allowlist, so it is never written."""
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        task_type="FE",
    )

    assert "task_type_id" not in response["updated_fields"]


async def test_update_task_ignores_task_type_immutable(db_session, two_tenant_service_setup):
    """BE-6049c: tasks are TSK-only and the tag is IMMUTABLE. update_task no
    longer validates/rejects an inbound task_type — it is silently ignored
    (task_type_id is not in the update allowlist), so passing even a bogus value
    is a harmless no-op rather than a hard error."""
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    # Pair the (ignored) task_type with a real field so this is a meaningful update.
    result = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        task_type="BOGUS",
        title="renamed",
    )
    assert "title" in result["updated_fields"]
    assert "task_type_id" not in result["updated_fields"]


async def test_update_task_rejects_invalid_status(db_session, two_tenant_service_setup):
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    with pytest.raises(ValidationError):
        await task_service_a.update_task_for_mcp(
            task_id=task_id,
            tenant_key=tenant_a,
            status="bogus",
        )


async def test_update_task_no_fields_returns_noop(db_session, two_tenant_service_setup):
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
    )

    assert response["updated_fields"] == []


# ---------------------------------------------------------------------------
# Phase D: list_tasks_for_mcp
# ---------------------------------------------------------------------------


async def test_list_tasks_summary_mode_returns_compact_rows(db_session, two_tenant_service_setup):
    """Summary mode carries at minimum the core identity + taxonomy parity fields.

    FE-5046 expanded the summary projection to mirror Project parity (added
    taxonomy_alias, series_number, subseries, hidden, embedded task_type
    block); keep the assertion as a subset check so additional fields don't
    regress the suite.
    """
    await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.list_tasks_for_mcp(
        tenant_key=tenant_a,
        mode="summary",
    )

    assert "tasks" in response
    assert len(response["tasks"]) >= 1
    row = response["tasks"][0]
    expected_keys = {"task_id", "title", "status", "priority", "task_type", "due_date", "created_at"}
    assert expected_keys.issubset(set(row.keys()))


async def test_list_tasks_filters_by_status(db_session, two_tenant_service_setup):
    pending_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    # Move one task to in_progress, leave the other pending.
    second_id = await _create_seed_task(db_session, two_tenant_service_setup)
    await task_service_a.update_task_for_mcp(
        task_id=second_id,
        status="in_progress",
        tenant_key=tenant_a,
    )

    response = await task_service_a.list_tasks_for_mcp(
        tenant_key=tenant_a,
        mode="summary",
        status="pending",
    )

    ids = {t["task_id"] for t in response["tasks"]}
    assert pending_id in ids
    assert second_id not in ids


async def test_list_tasks_filter_by_non_tsk_type_is_refused(db_session, two_tenant_service_setup):
    """BE-9470 (finding 5) superseded the old behaviour this test used to pin:
    tasks are TSK-only, so a non-TSK task_type filter structurally cannot match
    a single row. Before BE-9470 that silently answered matched:0 (indistinguishable
    from a genuine empty result, and self-contradicting against counts.by_type);
    it is now refused with why, the same U61 precedent applied to status/priority.
    task_type='TSK' is the one value that IS accepted -- see
    test_be9470_tasks_side.py for that coverage.
    """
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]
    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    await task_service_a.create_task_for_mcp(
        title="some work",
        description="",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )

    with pytest.raises(ValidationError, match="TSK"):
        await task_service_a.list_tasks_for_mcp(
            tenant_key=tenant_a,
            mode="summary",
            task_type="BE",
        )


async def test_list_tasks_is_tenant_scoped(db_session, two_tenant_service_setup):
    """A tenant_a request must not see tenant_b tasks."""
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tenant import TenantManager

    tenant_a = two_tenant_service_setup["tenant_a"]
    tenant_b = two_tenant_service_setup["tenant_b"]
    db_manager = two_tenant_service_setup["db_manager"]
    await _seed_taxonomy_for(db_session, tenant_b, db_manager)

    # Tenant B task
    task_service_b = TaskService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
    )
    b = await task_service_b.create_task_for_mcp(
        title="tenant_b task",
        description="x",
        task_type="BE",
        tenant_key=tenant_b,
        db_manager=db_manager,
    )

    # Tenant A task
    a_task_id = await _create_seed_task(db_session, two_tenant_service_setup)

    task_service_a = two_tenant_service_setup["task_service_a"]
    response = await task_service_a.list_tasks_for_mcp(
        tenant_key=tenant_a,
        mode="summary",
    )
    ids = {t["task_id"] for t in response["tasks"]}
    assert a_task_id in ids
    assert b["task_id"] not in ids


# ---------------------------------------------------------------------------
# FE-5046: Task UI parity -- hidden field + taxonomy projection
# ---------------------------------------------------------------------------


async def test_task_hidden_defaults_to_false_on_create(db_session, two_tenant_service_setup):
    """New tasks must have hidden=False unless explicitly set."""
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="full")
    row = next(r for r in response["tasks"] if r["task_id"] == task_id)
    assert row["hidden"] is False


async def test_update_task_hidden_round_trip_via_allowlist(db_session, two_tenant_service_setup):
    """Toggling hidden through update_task_for_mcp must persist."""
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    result = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
        hidden=True,
    )
    assert "hidden" in result["updated_fields"]

    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")
    row = next(r for r in response["tasks"] if r["task_id"] == task_id)
    assert row["hidden"] is True

    # Flip back
    await task_service_a.update_task_for_mcp(task_id=task_id, tenant_key=tenant_a, hidden=False)
    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")
    row = next(r for r in response["tasks"] if r["task_id"] == task_id)
    assert row["hidden"] is False


async def test_update_task_hidden_rejects_non_bool(db_session, two_tenant_service_setup):
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    with pytest.raises(ValidationError):
        await task_service_a.update_task_for_mcp(
            task_id=task_id,
            tenant_key=tenant_a,
            hidden="yes",  # type: ignore[arg-type]
        )


async def test_list_tasks_hidden_filter_semantics(db_session, two_tenant_service_setup):
    """hidden=None returns both; hidden=True/False filters explicitly."""
    visible_id = await _create_seed_task(db_session, two_tenant_service_setup)
    hidden_id = await _create_seed_task(db_session, two_tenant_service_setup)

    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await task_service_a.update_task_for_mcp(
        task_id=hidden_id,
        tenant_key=tenant_a,
        hidden=True,
    )

    # Default: both visible
    both = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")
    both_ids = {r["task_id"] for r in both["tasks"]}
    assert visible_id in both_ids
    assert hidden_id in both_ids

    only_hidden = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary", hidden=True)
    h_ids = {r["task_id"] for r in only_hidden["tasks"]}
    assert hidden_id in h_ids
    assert visible_id not in h_ids

    only_visible = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary", hidden=False)
    v_ids = {r["task_id"] for r in only_visible["tasks"]}
    assert visible_id in v_ids
    assert hidden_id not in v_ids


async def test_list_tasks_summary_row_has_taxonomy_parity_fields(db_session, two_tenant_service_setup):
    """Summary row must expose taxonomy_alias, series_number, subseries,
    embedded task_type block, and hidden -- the FE-5046 parity contract."""
    await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")
    row = response["tasks"][0]
    required = {"taxonomy_alias", "series_number", "subseries", "task_type", "hidden"}
    assert required.issubset(row.keys()), f"Missing keys: {required - set(row.keys())}"
    # task_type must be the embedded block (BE-6049c: every task is TSK)
    assert isinstance(row["task_type"], dict)
    assert {"id", "abbreviation", "label", "color"}.issubset(row["task_type"].keys())
    assert row["task_type"]["abbreviation"] == "TSK"
    # taxonomy_alias is a non-empty TSK-NNNN string for every task
    assert row["taxonomy_alias"].startswith("TSK-")
    assert isinstance(row["series_number"], int)


async def test_list_tasks_full_row_has_taxonomy_parity_fields(db_session, two_tenant_service_setup):
    await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="full")
    row = response["tasks"][0]
    required = {"taxonomy_alias", "series_number", "subseries", "task_type", "hidden"}
    assert required.issubset(row.keys()), f"Missing keys: {required - set(row.keys())}"


# ---------------------------------------------------------------------------
# BE-6077: list_tasks_for_mcp is product-scoped (parity with list_projects)
# ---------------------------------------------------------------------------


async def test_list_tasks_is_scoped_to_active_product(db_session, two_tenant_service_setup):
    """A task bound to a NON-active product of the SAME tenant must not appear.

    Regression for BE-6077: list_tasks_for_mcp previously filtered by tenant_key
    only, so an agent "on the active product" saw the whole tenant's task corpus
    (diverging from both the UI and list_projects). The query must now scope to
    tenant_key AND the active product's id.
    """
    from uuid import uuid4

    from giljo_mcp.models.products import Product
    from giljo_mcp.models.tasks import Task

    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    # Task under the ACTIVE product (product_a) via the normal create path.
    active_task_id = await _create_seed_task(db_session, two_tenant_service_setup)

    # A second, NON-active product for the same tenant, with a task bound to it.
    other_product = Product(
        id=str(uuid4()),
        name="Tenant A second (inactive) product",
        description="Holds a task that must not leak into the active product's list",
        tenant_key=tenant_a,
        is_active=False,
    )
    db_session.add(other_product)
    await db_session.commit()

    other_task = Task(
        id=str(uuid4()),
        tenant_key=tenant_a,
        product_id=other_product.id,
        title="task on the other product",
        description="should be invisible while product_a is active",
        status="pending",
        priority="medium",
    )
    db_session.add(other_task)
    await db_session.commit()

    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")

    ids = {t["task_id"] for t in response["tasks"]}
    assert active_task_id in ids, "active product's task must be listed"
    assert str(other_task.id) not in ids, "non-active product's task must NOT leak"
    # The response advertises which product it scoped to (parity with list_projects).
    assert response["product_id"] == product_a.id


async def test_list_tasks_requires_active_product(db_session, db_manager):
    """With no active product set, list_tasks_for_mcp raises (parity with list_projects)."""
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tenant import TenantManager

    tenant_key = TenantManager.generate_tenant_key()
    task_service = TaskService(
        db_manager=db_manager,
        tenant_manager=TenantManager(),
        session=db_session,
    )

    with pytest.raises(ValidationError) as excinfo:
        await task_service.list_tasks_for_mcp(tenant_key=tenant_key, mode="summary")

    assert "active product" in str(excinfo.value).lower()
