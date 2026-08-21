# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9469 follow-up -- black-box QA (units U59-U62) swept every list_tasks/list_projects
filter with garbage inputs and found the read layer answering some of them in a
self-contradicting, silently-wrong voice instead of refusing.

Fix 1/2 (U61-F1/U62-F1) -- ``TaskService.list_tasks_for_mcp`` never validated ``status``
or ``priority`` on the READ path, even though the exact same values ARE validated on the
WRITE path (``update_task_for_mcp``, ``_mcp_adapter_mixin.py:278``). A typo'd status or a
differently-cased priority returned ``matched:0`` -- byte-indistinguishable from a genuine
empty result, and directly contradicted by the SAME response's ``counts.by_status`` block.
This module reproduces the measured QA probes at the service layer, the layer the missing
validation call lives at.

Fix 3 (U62-F2) -- ``list_tasks``'s ``hidden`` coercion (in the @mcp.tool wrapper,
``api/endpoints/mcp_tools/_task_tools.py``) silently fell through to "no filter" on any
value outside its recognized true/false spellings. Reproduced at the MCP-boundary wrapper
itself, the layer this one lives at.

Fix 4 (U59-F1/U60-F1/U61-F2) -- three ``list_projects`` wire-schema declarations that
mislead an agent before it ever calls: a max_length cap 10x the enforced one, an
undiscoverable ``mode`` enum, and two undeclared/disagreeing status vocabularies.
Reproduced by reading the live FastMCP tool registry's published parameter schema, exactly
what an agent sees before calling.

Edition Scope: Both.
"""

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


# ---------------------------------------------------------------------------
# Fix 1 -- list_tasks.status: an invalid/typo'd status must REFUSE, never
# silently answer matched:0 while counts.by_status shows real rows.
# ---------------------------------------------------------------------------


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
        """QA's exact probe: 'in progress' (space) instead of 'in_progress'.

        Before the fix this returned matched:0 while counts.by_status.in_progress
        was nonzero in the SAME response -- a self-contradicting wrong answer.
        """
        task_id = await _create_task(two_tenant_service_setup, db_session)
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]
        await task_service_a.update_task_for_mcp(task_id=task_id, status="in_progress", tenant_key=tenant_a)

        # Prove the board genuinely has a matching row under the real spelling, so
        # an empty answer under the typo'd spelling would be self-contradictory.
        real = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", status="in_progress")
        assert real["counts"]["matched"] == 1

        with pytest.raises(ValidationError, match="in progress"):
            await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", status="in progress")


# ---------------------------------------------------------------------------
# Fix 2 -- list_tasks.priority: an invalid priority must REFUSE; a
# differently-cased VALID priority must match the same rows, not zero.
# ---------------------------------------------------------------------------


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
        """QA's exact probe: 'Medium' must match what 'medium' matches, not 0."""
        await _create_task(two_tenant_service_setup, db_session, priority="medium")
        tenant_a = two_tenant_service_setup["tenant_a"]
        task_service_a = two_tenant_service_setup["task_service_a"]

        lower = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", priority="medium")
        upper = await task_service_a.list_tasks_for_mcp(tenant_key=tenant_a, mode="index", priority="Medium")

        assert lower["counts"]["matched"] >= 1
        assert upper["counts"]["matched"] == lower["counts"]["matched"]


# ---------------------------------------------------------------------------
# Fix 3 -- list_tasks.hidden: garbage must REFUSE, not silently degrade to
# "no filter" (the real true/false coercions must keep working).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestListTasksHiddenFilterValidation:
    async def test_garbage_hidden_is_refused_at_the_wrapper_boundary(self, monkeypatch):
        """Stub ``_call_tool`` so a non-refusing wrapper cleanly falls through to a
        return value instead of crashing on the unrelated ctx=None dispatch path --
        the assertion under test is ONLY "did the wrapper refuse", nothing else."""
        from api.endpoints.mcp_tools import _task_tools

        async def _fake_call_tool(ctx, tool_name, kwargs):
            return {"tasks": [], "count": 0}

        monkeypatch.setattr(_task_tools, "_call_tool", _fake_call_tool)

        with pytest.raises(ValidationError, match="bogus_hidden_be9469"):
            await _task_tools.list_tasks(hidden="bogus_hidden_be9469")

    async def test_true_and_false_coercions_still_work(self, db_session, two_tenant_service_setup, monkeypatch):
        """The real coercion layer (true/1/yes, false/0/no, case-insensitive) must survive."""
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


# ---------------------------------------------------------------------------
# Fix 4 -- list_projects schema declarations: query's cap, mode's enum, and
# status/status_filter's vocabularies must be discoverable on the wire BEFORE
# an agent calls, and must match what the service actually enforces.
# ---------------------------------------------------------------------------


class TestListProjectsSchemaDeclarations:
    @staticmethod
    def _list_projects_schema() -> dict:
        from api.endpoints.mcp_sdk_server import mcp

        for tool in mcp._tool_manager.list_tools():
            if tool.name == "list_projects":
                return tool.parameters
        raise AssertionError("list_projects not found in the live tool registry")

    def test_query_declared_cap_matches_the_enforced_200(self):
        """U59-F1: the schema advertised maxLength:2000 while the service enforces 200."""
        schema = self._list_projects_schema()
        assert schema["properties"]["query"]["maxLength"] == 200

    def test_mode_enum_is_discoverable_on_the_wire(self):
        """U60-F1: the four legal mode values (plus '' for numeric depth) must be a
        published enum, not discoverable only via a failed call."""
        schema = self._list_projects_schema()
        mode_schema = schema["properties"]["mode"]
        declared = set(mode_schema.get("enum") or [])
        assert declared == {"", "triage", "planning", "audit", "forensic"}

    def test_status_description_names_its_real_vocabulary(self):
        """U61-F2: status's 8-value vocabulary (_VALID_FILTER_STATUSES) must be published."""
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
        """U61-F2: status_filter's 6-value vocabulary (_VALID_STATUS_FILTERS) differs from
        status's and must be published under its own name, not silently assumed identical."""
        schema = self._list_projects_schema()
        description = schema["properties"]["status_filter"].get("description", "")
        for value in ("active", "all", "cancelled", "completed", "inactive", "parked"):
            assert value in description, f"status_filter description does not name '{value}'"
