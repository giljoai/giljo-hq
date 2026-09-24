# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.taxonomy_service import TaxonomyService


pytestmark = pytest.mark.asyncio


async def _seed_taxonomy_for(db_session, tenant_key: str, db_manager) -> None:
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




async def test_create_task_for_mcp_forces_tsk_tag(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="Investigate flaky test",
        description="Repro and fix the websocket flake",
        priority="high",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )

    assert response["success"] is True
    assert response["task_id"]
    assert response["task_type"] == "TSK"
    assert response["taxonomy_alias"].startswith("TSK-")
    assert "valid_types" not in response


async def test_create_task_for_mcp_unknown_task_type_is_refused(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    with pytest.raises(ValidationError, match="MADEUP") as excinfo:
        await task_service_a.create_task_for_mcp(
            title="garbage type",
            description="an unknown task_type is refused, not absorbed",
            task_type="MADEUP",
            tenant_key=tenant_a,
            db_manager=db_manager,
        )
    assert "TSK" in excinfo.value.message
    assert "HND" in excinfo.value.message


async def test_create_task_for_mcp_accepts_the_handover_type(db_session, two_tenant_service_setup):
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="Session handover",
        description=(
            "Stopped at the rebase.\n\n"
            "## Verify before trusting\n- branch is green -- check with: pytest -q\n\n"
            "## Waiting on the operator\n- nothing\n\n"
            "## Cannot testify\n- the concurrency behaviour"
        ),
        task_type="HND",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )

    assert response["success"] is True
    assert response["task_type"] == "HND"
    assert response["taxonomy_alias"].startswith("HND-")


async def test_create_task_for_mcp_omitted_task_type_still_forces_tsk(db_session, two_tenant_service_setup):
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




async def _create_seed_task(db_session, two_tenant_service_setup) -> str:
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]
    await _seed_taxonomy_for(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="seed task",
        description="for status updates",
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    return response["task_id"]


async def test_update_task_status_field_transitions_to_in_progress(db_session, two_tenant_service_setup):
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
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
    )

    assert "task_type_id" not in response["updated_fields"]


async def test_update_task_ignores_task_type_immutable(db_session, two_tenant_service_setup):
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    result = await task_service_a.update_task_for_mcp(
        task_id=task_id,
        tenant_key=tenant_a,
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




async def test_list_tasks_summary_mode_returns_compact_rows(db_session, two_tenant_service_setup):
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
    expected_keys = {"task_id", "title", "status", "priority", "task_type", "created_at"}
    assert expected_keys.issubset(set(row.keys()))


async def test_list_tasks_filters_by_status(db_session, two_tenant_service_setup):
    pending_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

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
    b = await task_service_b.create_task_for_mcp(
        title="tenant_b task",
        description="x",
        tenant_key=tenant_b,
        db_manager=db_manager,
    )

    a_task_id = await _create_seed_task(db_session, two_tenant_service_setup)

    task_service_a = two_tenant_service_setup["task_service_a"]
    response = await task_service_a.list_tasks_for_mcp(
        tenant_key=tenant_a,
        mode="summary",
    )
    ids = {t["task_id"] for t in response["tasks"]}
    assert a_task_id in ids
    assert b["task_id"] not in ids




async def test_task_hidden_defaults_to_false_on_create(db_session, two_tenant_service_setup):
    task_id = await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="full")
    row = next(r for r in response["tasks"] if r["task_id"] == task_id)
    assert row["hidden"] is False


async def test_update_task_hidden_round_trip_via_allowlist(db_session, two_tenant_service_setup):
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
    visible_id = await _create_seed_task(db_session, two_tenant_service_setup)
    hidden_id = await _create_seed_task(db_session, two_tenant_service_setup)

    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    await task_service_a.update_task_for_mcp(
        task_id=hidden_id,
        tenant_key=tenant_a,
        hidden=True,
    )

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
    await _create_seed_task(db_session, two_tenant_service_setup)
    tenant_a = two_tenant_service_setup["tenant_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    response = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="summary")
    row = response["tasks"][0]
    required = {"taxonomy_alias", "series_number", "subseries", "task_type", "hidden"}
    assert required.issubset(row.keys()), f"Missing keys: {required - set(row.keys())}"
    assert isinstance(row["task_type"], dict)
    assert {"id", "abbreviation", "label", "color"}.issubset(row["task_type"].keys())
    assert row["task_type"]["abbreviation"] == "TSK"
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




async def test_list_tasks_is_scoped_to_active_product(db_session, two_tenant_service_setup):
    from uuid import uuid4

    from giljo_mcp.models.products import Product
    from giljo_mcp.models.tasks import Task

    tenant_a = two_tenant_service_setup["tenant_a"]
    product_a = two_tenant_service_setup["product_a"]
    task_service_a = two_tenant_service_setup["task_service_a"]

    active_task_id = await _create_seed_task(db_session, two_tenant_service_setup)

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
    assert response["product_id"] == product_a.id


async def test_list_tasks_requires_active_product(db_session, db_manager):
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

    assert "default product" in str(excinfo.value).lower()
