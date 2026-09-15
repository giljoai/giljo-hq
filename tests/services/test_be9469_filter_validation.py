# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.services.taxonomy_service import TaxonomyService


async def _seed_be_taxonomy(db_session, tenant_key: str, db_manager) -> None:
    service = TaxonomyService(db_manager=db_manager, session=db_session)
    existing = {row.abbreviation for row in await service.list_types(tenant_key)}
    if "BE" not in existing:
        await service.create_type(tenant_key=tenant_key, abbreviation="BE", label="Backend", sort_order=0)
    await db_session.commit()


async def _create_task(two_tenant_service_setup, db_session, *, priority: str = "medium") -> str:
    tenant_a = two_tenant_service_setup["tenant_a"]
    db_manager = two_tenant_service_setup["db_manager"]
    task_service_a = two_tenant_service_setup["task_service_a"]
    await _seed_be_taxonomy(db_session, tenant_a, db_manager)

    response = await task_service_a.create_task_for_mcp(
        title="BE-9469 filter validation seed task",
        description="seed",
        task_type="BE",
        priority=priority,
        tenant_key=tenant_a,
        db_manager=db_manager,
    )
    return response["task_id"]




@pytest.mark.asyncio
class TestListTasksStatusFilterValidation:
    async def test_unknown_status_is_refused(self, db_session, two_tenant_service_setup):
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        with pytest.raises(ValidationError, match="bogus_status_be9469"):
            await task_service_a.list_tasks_for_mcp(
                tenant_key=tenant_a,
                mode="index",
                status="bogus_status_be9469",
            )

    async def test_the_measured_natural_typo_is_refused_not_silently_empty(self, db_session, two_tenant_service_setup):
        task_id = await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]
        await task_service_a.update_task_for_mcp(task_id=task_id, status="in_progress", tenant_key=tenant_a)

        real = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", status="in_progress")
        assert real["counts"]["matched"] == 1

        with pytest.raises(ValidationError, match="in progress"):
            await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", status="in progress")




@pytest.mark.asyncio
class TestListTasksPriorityFilterValidation:
    async def test_unknown_priority_is_refused(self, db_session, two_tenant_service_setup):
        await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        with pytest.raises(ValidationError, match="bogus_priority_be9469"):
            await task_service_a.list_tasks_for_mcp(
                tenant_key=tenant_a,
                mode="index",
                priority="bogus_priority_be9469",
            )

    async def test_uppercase_priority_matches_the_same_rows_as_lowercase(self, db_session, two_tenant_service_setup):
        await _create_task(two_tenant_service_setup, db_session, priority="medium")
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        lower = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", priority="medium")
        upper = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", priority="Medium")

        assert lower["counts"]["matched"] >= 1
        assert upper["counts"]["matched"] == lower["counts"]["matched"]




@pytest.mark.asyncio
class TestListTasksHiddenFilterValidation:
    async def test_garbage_hidden_is_refused_at_the_wrapper_boundary(self, monkeypatch):
        from api.endpoints.mcp_tools import _task_tools

        async def _fake_call_tool(ctx, tool_name, kwargs):
            return {"tasks": [], "count": 0}

        monkeypatch.setattr(_task_tools, "_call_tool", _fake_call_tool)

        with pytest.raises(ValidationError, match="bogus_hidden_be9469"):
            await _task_tools.list_tasks(hidden="bogus_hidden_be9469")

    async def test_true_and_false_coercions_still_work(self, db_session, two_tenant_service_setup, monkeypatch):
        from api.endpoints.mcp_tools import _task_tools

        seen: dict[str, object] = {}

        async def _fake_call_tool(ctx, tool_name, kwargs):
            seen["kwargs"] = kwargs
            return {}

        monkeypatch.setattr(_task_tools, "_call_tool", _fake_call_tool)

        await _task_tools.list_tasks(hidden="True")
        assert seen["kwargs"]["hidden"] is True

        await _task_tools.list_tasks(hidden="0")
        assert seen["kwargs"]["hidden"] is False

        await _task_tools.list_tasks(hidden="")
        assert "hidden" not in seen["kwargs"]




class TestListProjectsSchemaDeclarations:
    @staticmethod
    def _list_projects_schema() -> dict:
        from api.endpoints.mcp_sdk_server import mcp

        for tool in mcp._tool_manager.list_tools():
            if tool.name == "list_projects":
                return tool.parameters
        raise AssertionError("list_projects not found in the live tool registry")

    def test_query_declared_cap_matches_the_enforced_200(self):
        schema = self._list_projects_schema()
        assert schema["properties"]["query"]["maxLength"] == 200

    def test_mode_enum_is_discoverable_on_the_wire(self):
        schema = self._list_projects_schema()
        mode_schema = schema["properties"]["mode"]
        declared = set(mode_schema.get("enum") or [])
        assert declared == {"", "triage", "planning", "audit", "forensic"}

    def test_status_description_names_its_real_vocabulary(self):
        schema = self._list_projects_schema()
        description = schema["properties"]["status"].get("description", "")
        for value in (
            "active",
            "cancelled",
            "completed",
            "deleted",
            "inactive",
            "parked",
            "superseded",
            "terminated",
        ):
            assert value in description, f"status description does not name '{value}'"

    def test_status_filter_description_names_its_real_vocabulary(self):
        schema = self._list_projects_schema()
        description = schema["properties"]["status_filter"].get("description", "")
        for value in ("active", "all", "cancelled", "completed", "inactive", "parked"):
            assert value in description, f"status_filter description does not name '{value}'"
