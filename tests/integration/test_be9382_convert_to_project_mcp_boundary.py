# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9382 — ``update_task(convert_to_project=True)`` MCP-boundary regression test.

Gap closed: an agent could not promote a task to a project headlessly. The
documented compose-it-yourself recipe (create_project + complete the task +
re-point the roadmap by hand) produced DIFFERENT semantics from the dashboard's
convert wizard — task kept instead of deleted, and a forgotten roadmap re-point
silently orphaned the roadmap card. Mechanism gap, not a prose gap.

Fix: ``update_task`` gained a ``convert_to_project`` flag wired to the SAME
``TaskConversionService.convert_to_project`` the REST ``POST /tasks/{id}/convert``
(the UI door) calls, with the UI's exact request defaults (strategy="single",
include_subtasks=True). No parallel implementation.

Tested THROUGH THE MCP TRANSPORT (BE-5042 precedent: the failing layer for a
@mcp.tool wrapper is the wrapper, and ~1,392 unit tests did not see it) via the
SDK's in-memory ``create_connected_server_and_client_session``. Pattern
reference: ``tests/integration/test_task_tools_mcp_transport.py``.

Coverage:
- convert → task row GONE, project exists (inactive + UNTYPED, task's title and
  serial), subtasks re-pointed, roadmap item flipped IN PLACE with an identical
  ``sort_order``, response says unmistakably that the task is deleted.
- ``title`` on a convert names the new project (UI wizard's project_name field).
- convert + a conflicting task field (status / completion_notes / priority) →
  BE-6081 Tier-2 structured rejection, NOT isError, and nothing written.
- convert with no resolvable authenticated user → Tier-2 USER_CONTEXT_REQUIRED.
- a plain (non-convert) ``update_task`` response is unchanged — no convert keys.

Isolation: the ToolAccessor's TaskService is bound to the rollback-isolated
``db_session``, so every write (including the conversion's own commit-owning
scope) stays inside the test transaction (``optional_tenant_session`` yields the
injected session without committing).
"""

from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.models.roadmaps import Roadmap, RoadmapItem
from giljo_mcp.models.tasks import Task
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

_ROADMAP_SORT_ORDER = 7  # deliberately non-zero: proves "in place", not "re-ranked to 0"


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


def _error_text(call_tool_result) -> str:
    parts = []
    for block in call_tool_result.content or []:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


class _Seeded:
    """The row ids one seeded promotion scenario needs."""

    def __init__(self, *, user_id: str, product_id: str, task_id: str, subtask_id: str, roadmap_item_id: str):
        self.user_id = user_id
        self.product_id = product_id
        self.task_id = task_id
        self.subtask_id = subtask_id
        self.roadmap_item_id = roadmap_item_id


async def _seed_promotable_task(db_session, tenant_key: str) -> _Seeded:
    """Commit (inside the test transaction) an active product + TSK-tagged task
    with one subtask and one roadmap card pointing at the task."""
    suffix = uuid4().hex[:8]

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    user = User(
        id=str(uuid4()),
        username=f"be9382_{suffix}",
        email=f"be9382_{suffix}@example.com",
        tenant_key=tenant_key,
        role="developer",
        password_hash="hashed_password",
        org_id=org.id,
    )
    product = Product(
        id=str(uuid4()),
        name=f"BE9382 Product {suffix}",
        description="product for the convert_to_project boundary test",
        tenant_key=tenant_key,
        is_active=True,
    )
    tsk_type = TaxonomyType(
        id=str(uuid4()),
        tenant_key=tenant_key,
        abbreviation="TSK",
        label="Task",
        sort_order=0,
    )
    db_session.add_all([user, product, tsk_type])
    await db_session.flush()

    task = Task(
        id=str(uuid4()),
        tenant_key=tenant_key,
        org_id=org.id,
        product_id=product.id,
        created_by_user_id=user.id,
        task_type_id=tsk_type.id,
        title="Rate limiter keeps dropping bursts",
        description="Bigger than a task once we looked at it.",
        status="pending",
        priority="high",
        series_number=random.randint(1, 9000),
    )
    db_session.add(task)
    await db_session.flush()

    subtask = Task(
        id=str(uuid4()),
        tenant_key=tenant_key,
        org_id=org.id,
        product_id=product.id,
        created_by_user_id=user.id,
        parent_task_id=task.id,
        task_type_id=tsk_type.id,
        title="Child of the promoted task",
        description="must follow its parent to the new project",
        status="pending",
    )
    roadmap = Roadmap(id=str(uuid4()), tenant_key=tenant_key, product_id=product.id)
    db_session.add_all([subtask, roadmap])
    await db_session.flush()

    item = RoadmapItem(
        id=str(uuid4()),
        tenant_key=tenant_key,
        roadmap_id=roadmap.id,
        item_type="task",
        task_id=task.id,
        sort_order=_ROADMAP_SORT_ORDER,
        risk="high",
        complexity="med",
    )
    db_session.add(item)
    await db_session.commit()

    return _Seeded(
        user_id=user.id,
        product_id=product.id,
        task_id=task.id,
        subtask_id=subtask.id,
        roadmap_item_id=item.id,
    )


class _Resolved:
    """Mutable holder for the identity the patched resolvers hand the wrappers."""

    def __init__(self, tenant_key: str):
        self.tenant_key = tenant_key
        self.user_id: str | None = None


@pytest_asyncio.fixture
async def convert_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, resolved, tenant_key)``.

    The ToolAccessor's TaskService is bound to the rollback-isolated
    ``db_session`` so the conversion's writes stay inside the test transaction.
    ``resolved.user_id`` is what ``_resolve_user_id`` returns (production reads it
    from the ASGI scope; there is no HTTP scope on the in-memory transport).
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.task_service import TaskService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)
    accessor._task_service = TaskService(
        db_manager=db_manager,
        tenant_manager=state.tenant_manager,
        session=db_session,
    )
    state.tool_accessor = accessor

    resolved = _Resolved(tenant_key)
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: resolved.tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: resolved.user_id)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, resolved, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


class TestConvertToProjectMcpBoundary:
    async def test_convert_deletes_task_and_repoints_everything(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task",
                {"task_id": seeded.task_id, "convert_to_project": True},
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

        # The response must make the deletion UNMISTAKABLE and hand back a usable project.
        assert payload["success"] is True, payload
        assert payload["converted_to_project"] is True, payload
        assert payload["task_deleted"] is True, payload
        assert payload["task_exists"] is False, payload
        new_project_id = payload["project_id"]
        assert new_project_id, payload
        assert payload["project_name"] == "Rate limiter keeps dropping bursts"
        assert payload["taxonomy_alias"], "the promoted project's alias must be returned"
        assert payload["project_type"] is None, "conversion strips the type (IMP-6262)"
        assert "deleted" in payload["message"].lower()

        # Task row is GONE (hard delete, not a status flip).
        gone = (await db_session.execute(select(Task.id).where(Task.id == seeded.task_id))).scalar_one_or_none()
        assert gone is None, "the converted task row must be hard-deleted"

        # Project exists, inactive, untyped, carrying the task's identity.
        project = (await db_session.execute(select(Project).where(Project.id == new_project_id))).scalar_one_or_none()
        assert project is not None, "the promoted project must exist"
        assert project.tenant_key == tenant_key
        assert project.product_id == seeded.product_id
        assert project.status == "inactive"
        assert project.project_type_id is None
        assert project.series_number is not None

        # Subtask followed its parent.
        subtask_project = (
            await db_session.execute(select(Task.project_id).where(Task.id == seeded.subtask_id))
        ).scalar_one()
        assert subtask_project == new_project_id

        # Roadmap card re-pointed IN PLACE: same row, same sort_order, discriminator flipped.
        item_row = (
            await db_session.execute(
                select(
                    RoadmapItem.item_type,
                    RoadmapItem.project_id,
                    RoadmapItem.task_id,
                    RoadmapItem.sort_order,
                ).where(RoadmapItem.id == seeded.roadmap_item_id)
            )
        ).one_or_none()
        assert item_row is not None, "the roadmap card must survive the conversion (ce_0047 CASCADE)"
        item_type, item_project_id, item_task_id, sort_order = item_row
        assert item_type == "project"
        assert item_project_id == new_project_id
        assert item_task_id is None
        assert sort_order == _ROADMAP_SORT_ORDER, "conversion must never reorder the roadmap"

    async def test_title_names_the_new_project(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task",
                {
                    "task_id": seeded.task_id,
                    "convert_to_project": True,
                    "title": "Rebuild the rate limiter",
                },
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["project_name"] == "Rebuild the rate limiter"

        name = (await db_session.execute(select(Project.name).where(Project.id == payload["project_id"]))).scalar_one()
        assert name == "Rebuild the rate limiter"

    @pytest.mark.parametrize(
        "conflicting",
        [
            {"status": "completed"},
            {"completion_notes": "done enough"},
            {"priority": "low"},
            {"hidden": "true"},
        ],
    )
    async def test_conflicting_field_is_a_structured_rejection_that_writes_nothing(
        self, convert_client, db_session, conflicting
    ):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task",
                {"task_id": seeded.task_id, "convert_to_project": True, **conflicting},
            )

        # BE-6081 Tier 2: a deliberate, agent-actionable rejection is normal
        # content, never isError.
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["success"] is False, payload
        assert payload["error"] == "CONVERT_FIELD_CONFLICT", payload
        assert set(payload["conflicting_fields"]) == set(conflicting), payload

        # Nothing written: the task still exists, unmodified, and no project appeared.
        row = (
            await db_session.execute(
                select(Task.status, Task.priority, Task.hidden, Task.converted_to_project_id).where(
                    Task.id == seeded.task_id
                )
            )
        ).one_or_none()
        assert row is not None, "a refused convert must not delete the task"
        assert row.status == "pending"
        assert row.priority == "high"
        assert bool(row.hidden) is False
        assert row.converted_to_project_id is None

        project_count = (
            await db_session.execute(
                select(Project.id).where(Project.tenant_key == tenant_key, Project.product_id == seeded.product_id)
            )
        ).all()
        assert project_count == [], "a refused convert must not create a project"

    async def test_convert_without_authenticated_user_is_a_structured_rejection(self, convert_client, db_session):
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = None  # legacy API key: no user_id back-reference

        async with new_client() as session:
            result = await session.call_tool(
                "update_task",
                {"task_id": seeded.task_id, "convert_to_project": True},
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert payload["success"] is False, payload
        assert payload["error"] == "USER_CONTEXT_REQUIRED", payload

        still_there = (await db_session.execute(select(Task.id).where(Task.id == seeded.task_id))).scalar_one_or_none()
        assert still_there == seeded.task_id

    async def test_plain_update_task_response_carries_no_convert_keys(self, convert_client, db_session):
        """Non-convert behavior is unchanged: same three keys, no convert surface."""
        new_client, resolved, tenant_key = convert_client
        seeded = await _seed_promotable_task(db_session, tenant_key)
        resolved.user_id = seeded.user_id

        async with new_client() as session:
            result = await session.call_tool(
                "update_task",
                {"task_id": seeded.task_id, "title": "just a rename", "status": "in_progress"},
            )

        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
        assert set(payload) - {"_meta"} == {"task_id", "updated_fields", "message"}, payload
        assert payload["task_id"] == seeded.task_id
        assert "title" in payload["updated_fields"]
        assert "status" in payload["updated_fields"]

        row = (await db_session.execute(select(Task.title, Task.status).where(Task.id == seeded.task_id))).one_or_none()
        assert row is not None, "a plain update must not delete the task"
        assert row.title == "just a rename"
        assert row.status == "in_progress"
