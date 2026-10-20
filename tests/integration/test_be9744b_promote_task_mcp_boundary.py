# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import pytest
from sqlalchemy import select

from giljo_mcp.exceptions import ValidationError
from giljo_mcp.models.projects import Project
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.integration import test_be9382_convert_to_project_mcp_boundary as _harness


_error_text = _harness._error_text
_payload = _harness._payload
_seed_promotable_task = _harness._seed_promotable_task
convert_client = _harness.convert_client

pytestmark = pytest.mark.asyncio


async def _task_row(db_session, task_id: str):
    return (
        await db_session.execute(
            select(Task.title, Task.status, Task.priority, Task.converted_to_project_id).where(Task.id == task_id)
        )
    ).one_or_none()


async def _project_count(db_session, tenant_key: str, product_id: str) -> int:
    rows = (
        await db_session.execute(
            select(Project.id).where(Project.tenant_key == tenant_key, Project.product_id == product_id)
        )
    ).all()
    return len(rows)


class TestPromoteTaskToProject:
    async def test_promotes_through_the_new_tool(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool("promote_task_to_project", {"task_id": seeded.task_id})

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["success"] is True, payload
        assert payload["task_deleted"] is True, payload
        assert payload["product_id"] == seeded.product_id
        assert payload["project_status"] == "inactive"
        assert await _task_row(db_session, seeded.task_id) is None, "the promoted task row must be deleted"

    async def test_title_names_the_new_project(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "promote_task_to_project", {"task_id": seeded.task_id, "title": "Rebuild the rate limiter"}
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["project_name"] == "Rebuild the rate limiter"

    async def test_other_tenants_task_is_refused_and_untouched(self, convert_client, db_session):
        new_client, resolved, _tenant_key = convert_client
        other_tenant = TenantManager.generate_tenant_key()
        foreign = await _seed_promotable_task(db_session, other_tenant)
        resolved.user_id = foreign.user_id

        async with new_client() as session:
            result = await session.call_tool("promote_task_to_project", {"task_id": foreign.task_id})

        assert result.is_error, f"another tenant's task must be refused: {result.content!r}"
        assert "task not found" in _error_text(result).lower(), _error_text(result)
        row = await _task_row(db_session, foreign.task_id)
        assert row is not None and row.converted_to_project_id is None, "the foreign task must be untouched"
        assert await _project_count(db_session, other_tenant, foreign.product_id) == 0

    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_blank_title_is_refused_at_the_boundary(self, convert_client, db_session, blank):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool("promote_task_to_project", {"task_id": seeded.task_id, "title": blank})

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["success"] is False, payload
        assert payload["error"] == "VALIDATION_ERROR", payload
        assert payload["field"] == "title", payload
        assert "required and cannot be empty" in payload["message"], payload
        row = await _task_row(db_session, seeded.task_id)
        assert row is not None, "a refused promotion must not delete the task"
        assert await _project_count(db_session, tenant_key, seeded.product_id) == 0

    @pytest.mark.parametrize("blank", ["", "   "])
    async def test_blank_title_is_refused_in_the_service(self, db_manager, db_session, convert_client, blank):
        from giljo_mcp.services.task_service import TaskService

        _new_client, _resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        tenant_manager = TenantManager()
        service = TaskService(db_manager=db_manager, tenant_manager=tenant_manager, session=db_session)

        with pytest.raises(ValidationError, match="title"):
            await service.promote_task_for_mcp(
                task_id=seeded.task_id, tenant_key=tenant_key, title=blank, user_id=seeded.user_id
            )

        row = await _task_row(db_session, seeded.task_id)
        assert row is not None, "a refused promotion must not delete the task"
        assert await _project_count(db_session, tenant_key, seeded.product_id) == 0

    async def test_without_authenticated_user_is_a_structured_rejection(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = None

        async with new_client() as session:
            result = await session.call_tool("promote_task_to_project", {"task_id": seeded.task_id})

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["success"] is False, payload
        assert payload["error"] == "USER_CONTEXT_REQUIRED", payload
        assert await _task_row(db_session, seeded.task_id) is not None


class TestUpdateTaskNoLongerConverts:

    @pytest.mark.parametrize("extra", [{}, {"title": "A new name"}, {"status": "completed"}])
    async def test_convert_true_gets_the_pointer_and_changes_nothing(self, convert_client, db_session, extra):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id
        before = await _task_row(db_session, seeded.task_id)

        async with new_client() as session:
            result = await session.call_tool(
                "update_task", {"task_id": seeded.task_id, "convert_to_project": True, **extra}
            )

        assert result.is_error is False, f"a pointer is Tier-2 content, not isError: {_error_text(result)}"
        payload = _payload(result)
        assert payload["success"] is False, payload
        assert payload["error"] == "VALIDATION_ERROR", payload
        assert payload["field"] == "convert_to_project", payload
        assert payload["constraint"] == "retired_argument", payload
        assert "promote_task_to_project" in payload["message"], payload
        assert "Nothing was changed" in payload["message"], payload

        after = await _task_row(db_session, seeded.task_id)
        assert after == before, "the pointer must not write anything, not even the sibling title/status"
        assert await _project_count(db_session, tenant_key, seeded.product_id) == 0

    async def test_convert_false_is_a_harmless_plain_update(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task", {"task_id": seeded.task_id, "convert_to_project": False, "title": "just a rename"}
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload.get("error") is None, payload
        assert "title" in payload["updated_fields"], payload
        row = await _task_row(db_session, seeded.task_id)
        assert row is not None and row.title == "just a rename"
        assert await _project_count(db_session, tenant_key, seeded.product_id) == 0

    @pytest.mark.parametrize("value", ["true", "false", 1, None, ["true"]])
    async def test_a_non_boolean_value_is_not_silently_a_plain_update(self, convert_client, db_session, value):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task", {"task_id": seeded.task_id, "convert_to_project": value, "title": "must not land"}
            )

        payload = _payload(result)
        assert payload["error"] == "VALIDATION_ERROR", payload
        assert payload["field"] == "convert_to_project", payload
        assert "promote_task_to_project" in payload["message"], payload
        row = await _task_row(db_session, seeded.task_id)
        assert row is not None and row.title != "must not land"


class TestAdvertisedSurface:
    async def test_update_task_schema_no_longer_advertises_the_flag(self):
        from api.endpoints.mcp_sdk_server import mcp

        tool = mcp._tool_manager.get_tool("update_task")
        assert "convert_to_project" not in tool.parameters["properties"]
        assert "convert_to_project" not in tool.description
        assert "PROMOTE" not in tool.description

    async def test_promote_tool_is_registered_with_explicit_hints_and_tight_schema(self):
        from api.endpoints.mcp_sdk_server import mcp
        from api.endpoints.mcp_tools._base import TOOL_SCOPES

        tool = mcp._tool_manager.get_tool("promote_task_to_project")
        assert tool is not None, "promote_task_to_project is not registered"
        assert set(tool.parameters["properties"]) == {"task_id", "title"}
        assert tool.parameters["required"] == ["task_id"]
        assert tool.parameters["properties"]["task_id"]["maxLength"] == 64
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.open_world_hint is False
        assert tool.annotations.destructive_hint is True
        assert TOOL_SCOPES["promote_task_to_project"] == TOOL_SCOPES["update_task"]
        for phrase in ("deletes the task", "no longer resolves", "inactive", "untyped", "update_project"):
            assert phrase in tool.description.lower(), f"description must say: {phrase}"

    async def test_registry_has_exactly_54_tools(self):
        from api.endpoints.mcp_sdk_server import mcp

        assert len({t.name for t in mcp._tool_manager.list_tools()}) == 54


class TestRetiredArgumentHelperBooleanFlag:
    async def test_true_is_a_pointer_false_dispatches_and_other_tools_are_untouched(self):
        from api.endpoints.mcp_tools._retired_arguments import retired_argument_rejection

        pointer = retired_argument_rejection("update_task", {"task_id": "t", "convert_to_project": True})
        assert pointer["field"] == "convert_to_project"
        assert "promote_task_to_project" in pointer["message"]
        assert retired_argument_rejection("update_task", {"task_id": "t", "convert_to_project": False}) is None
        assert retired_argument_rejection("update_task", {"task_id": "t"}) is None
        assert retired_argument_rejection("create_task", {"convert_to_project": True}) is None
