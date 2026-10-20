# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommThread
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, TaxonomyType
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

RETIRED_TOOL = "resume_or_dismiss_job"


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


@pytest_asyncio.fixture
async def be9748_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.services.roadmap_service import RoadmapService
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    user = User(id=str(uuid4()), tenant_key=tenant_key, username=f"be9748_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    accessor._roadmap_service = RoadmapService(
        db_manager=db_manager, tenant_manager=state.tenant_manager, session=db_session
    )
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_product_and_projects(session, tenant_key: str, *, projects: int = 2) -> dict:
    product = Product(
        id=str(uuid4()),
        name=f"BE-9748 product {uuid4().hex[:6]}",
        description="tool split boundary test",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    session.add(product)
    await session.flush()
    rows = [
        Project(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"BE-9748 project {n}",
            description="tool split boundary test",
            mission="m",
            status="inactive",
            series_number=random.randint(1, 9000),
        )
        for n in range(projects)
    ]
    session.add_all(rows)
    await session.commit()
    return {"product_id": product.id, "project_ids": [p.id for p in rows]}


async def _seed_held_job(session, tenant_key: str, project_id: str, *, execution_status: str = "blocked") -> str:
    job = AgentJob(
        job_id=str(uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission="do work",
        status="completed",
    )
    session.add(job)
    session.add(
        AgentExecution(
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="implementer",
            status=execution_status,
            block_reason="a post that needs action" if execution_status == "blocked" else None,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
            completed_at=datetime.now(UTC),
            messages_sent_count=0,
            messages_waiting_count=0,
            messages_read_count=0,
        )
    )
    await session.commit()
    return job.job_id


async def _execution_status(session, job_id: str) -> str:
    session.expire_all()
    row = (await session.execute(select(AgentExecution).where(AgentExecution.job_id == job_id))).scalar_one()
    return row.status


async def _job_status(session, job_id: str) -> str:
    session.expire_all()
    return (await session.execute(select(AgentJob).where(AgentJob.job_id == job_id))).scalar_one().status


def _tool(name: str):
    from api.endpoints.mcp_sdk_server import mcp

    return mcp._tool_manager.get_tool(name)




class TestResumeAndDismissAreTwoTools:
    async def test_resume_job_sets_a_held_job_back_to_working(self, be9748_client):
        new_client, tenant_key, session = be9748_client
        seed = await _seed_product_and_projects(session, tenant_key)
        job_id = await _seed_held_job(session, tenant_key, seed["project_ids"][0])

        async with new_client() as s:
            res = await s.call_tool("resume_job", {"job_id": job_id, "reason": "rework requested"})
        assert res.is_error is False, _error_text(res)
        assert _payload(res).get("success") is not False, _payload(res)

        assert await _execution_status(session, job_id) == "working"
        assert await _job_status(session, job_id) == "active"

    async def test_dismiss_job_returns_a_held_job_to_complete(self, be9748_client):
        new_client, tenant_key, session = be9748_client
        seed = await _seed_product_and_projects(session, tenant_key)
        job_id = await _seed_held_job(session, tenant_key, seed["project_ids"][0])

        async with new_client() as s:
            res = await s.call_tool("dismiss_job", {"job_id": job_id})
        assert res.is_error is False, _error_text(res)

        assert await _execution_status(session, job_id) == "complete"
        assert await _job_status(session, job_id) == "completed"

    @pytest.mark.parametrize("tool_name", ["resume_job", "dismiss_job"])
    async def test_a_job_that_is_not_on_hold_is_refused_and_untouched(self, be9748_client, tool_name):
        new_client, tenant_key, session = be9748_client
        seed = await _seed_product_and_projects(session, tenant_key)
        job_id = await _seed_held_job(session, tenant_key, seed["project_ids"][0], execution_status="complete")

        async with new_client() as s:
            res = await s.call_tool(tool_name, {"job_id": job_id})
        assert res.is_error is True, _payload(res)
        assert "blocked" in _error_text(res).lower()
        assert await _execution_status(session, job_id) == "complete"

    async def test_the_switch_tool_is_gone(self, be9748_client):
        new_client, _tenant_key, _session = be9748_client
        assert _tool(RETIRED_TOOL) is None, f"{RETIRED_TOOL} must not be registered"
        async with new_client() as s:
            res = await s.call_tool(RETIRED_TOOL, {"job_id": "x", "action": "resume"})
        assert res.is_error is True
        assert "unknown tool" in _error_text(res).lower()

    @pytest.mark.parametrize("tool_name", ["resume_job", "dismiss_job"])
    async def test_schema_is_one_operation_with_explicit_hints(self, tool_name):
        tool = _tool(tool_name)
        assert tool is not None, f"{tool_name} is not registered"
        assert set(tool.parameters["properties"]) == {"job_id", "reason"}
        assert tool.parameters["required"] == ["job_id"]
        assert "action" not in tool.parameters["properties"]
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is False
        assert tool.annotations.open_world_hint is False




class TestRoadmapRemovalIsItsOwnTool:
    async def _rank_two(self, new_client, seed) -> None:
        items = [
            {"item_type": "project", "project_id": pid, "sort_order": i} for i, pid in enumerate(seed["project_ids"])
        ]
        async with new_client() as s:
            res = await s.call_tool("save_roadmap", {"items": items, "product_id": seed["product_id"]})
            assert res.is_error is False, _error_text(res)
            board = await s.call_tool("get_roadmap", {"product_id": seed["product_id"]})
        assert len(_payload(board)["items"]) == 2

    async def test_remove_roadmap_items_drops_only_the_named_entry(self, be9748_client):
        new_client, tenant_key, session = be9748_client
        seed = await _seed_product_and_projects(session, tenant_key)
        await self._rank_two(new_client, seed)

        async with new_client() as s:
            res = await s.call_tool(
                "remove_roadmap_items",
                {
                    "items": [{"item_type": "project", "project_id": seed["project_ids"][0]}],
                    "product_id": seed["product_id"],
                },
            )
            assert res.is_error is False, _error_text(res)
            assert _payload(res)["items_removed"] == 1
            board = _payload(await s.call_tool("get_roadmap", {"product_id": seed["product_id"]}))

        remaining = [item["project_id"] for item in board["items"]]
        assert remaining == [seed["project_ids"][1]]
        session.expire_all()
        still_there = await session.execute(select(Project).where(Project.id == seed["project_ids"][0]))
        assert still_there.scalar_one_or_none() is not None

    async def test_removing_a_ref_that_is_not_on_the_board_is_a_clean_no_op(self, be9748_client):
        new_client, tenant_key, session = be9748_client
        seed = await _seed_product_and_projects(session, tenant_key)
        await self._rank_two(new_client, seed)

        async with new_client() as s:
            res = await s.call_tool(
                "remove_roadmap_items",
                {"items": [{"item_type": "project", "project_id": str(uuid4())}], "product_id": seed["product_id"]},
            )
            board = _payload(await s.call_tool("get_roadmap", {"product_id": seed["product_id"]}))
        assert res.is_error is False, _error_text(res)
        assert _payload(res)["items_removed"] == 0
        assert len(board["items"]) == 2

    async def test_save_roadmap_with_remove_gets_the_pointer_and_changes_nothing(self, be9748_client):
        new_client, tenant_key, session = be9748_client
        seed = await _seed_product_and_projects(session, tenant_key)
        await self._rank_two(new_client, seed)

        async with new_client() as s:
            res = await s.call_tool(
                "save_roadmap",
                {
                    "items": [{"item_type": "project", "project_id": seed["project_ids"][1], "sort_order": 7}],
                    "remove": [{"item_type": "project", "project_id": seed["project_ids"][0]}],
                    "product_id": seed["product_id"],
                },
            )
            board = _payload(await s.call_tool("get_roadmap", {"product_id": seed["product_id"]}))

        assert res.is_error is False, f"a pointer is Tier-2 content, not isError: {res.content!r}"
        payload = _payload(res)
        assert payload["success"] is False
        assert payload["error"] == "VALIDATION_ERROR"
        assert payload["field"] == "remove"
        assert "remove_roadmap_items" in payload["message"]
        assert "Nothing was changed" in payload["message"]
        by_project = {item["project_id"]: item for item in board["items"]}
        assert set(by_project) == set(seed["project_ids"])
        assert by_project[seed["project_ids"][1]]["sort_order"] == 1

    @pytest.mark.parametrize("remove", [None, []])
    async def test_an_empty_remove_is_the_old_default_and_still_upserts(self, be9748_client, remove):
        new_client, tenant_key, session = be9748_client
        seed = await _seed_product_and_projects(session, tenant_key)

        async with new_client() as s:
            res = await s.call_tool(
                "save_roadmap",
                {
                    "items": [{"item_type": "project", "project_id": seed["project_ids"][0], "sort_order": 0}],
                    "remove": remove,
                    "product_id": seed["product_id"],
                },
            )
            board = _payload(await s.call_tool("get_roadmap", {"product_id": seed["product_id"]}))
        assert res.is_error is False, _error_text(res)
        assert _payload(res).get("error") != "VALIDATION_ERROR", _payload(res)
        assert len(board["items"]) == 1

    async def test_schemas_split_cleanly(self):
        save = _tool("save_roadmap")
        assert "remove" not in save.parameters["properties"]
        assert save.annotations.destructive_hint is True

        remove = _tool("remove_roadmap_items")
        assert remove is not None, "remove_roadmap_items is not registered"
        assert set(remove.parameters["properties"]) == {"items", "product_id"}
        assert remove.parameters["required"] == ["items"]
        assert remove.parameters["properties"]["items"]["minItems"] == 1
        assert remove.annotations.read_only_hint is False
        assert remove.annotations.destructive_hint is True
        assert remove.annotations.open_world_hint is False




async def _create_thread(new_client, subject: str) -> str:
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": subject, "creator_id": "alpha"})
    assert res.is_error is False, _error_text(res)
    return _payload(res)["thread_id"]


async def _subject(session, thread_id: str) -> str:
    session.expire_all()
    return (await session.execute(select(CommThread).where(CommThread.id == thread_id))).scalar_one().subject


async def _posted(session, thread_id: str, content: str):
    session.expire_all()
    return (
        await session.execute(select(Message).where(Message.thread_id == thread_id, Message.content == content))
    ).scalar_one_or_none()


class TestRenameLeftPostToThread:
    async def test_rename_to_gets_the_pointer_and_posts_nothing(self, be9748_client):
        new_client, _tenant_key, session = be9748_client
        tid = await _create_thread(new_client, "original subject")

        async with new_client() as s:
            res = await s.call_tool(
                "post_to_thread",
                {"thread_id": tid, "content": "renaming this thread", "from_agent": "alpha", "rename_to": "new"},
            )
        assert res.is_error is False, f"a pointer is Tier-2 content, not isError: {res.content!r}"
        payload = _payload(res)
        assert payload["success"] is False
        assert payload["error"] == "VALIDATION_ERROR"
        assert payload["field"] == "rename_to"
        assert "update_thread" in payload["message"]
        assert "Nothing was changed" in payload["message"]

        assert await _subject(session, tid) == "original subject"
        assert await _posted(session, tid, "renaming this thread") is None

    async def test_an_empty_rename_to_is_the_old_default_and_still_posts(self, be9748_client):
        new_client, _tenant_key, session = be9748_client
        tid = await _create_thread(new_client, "kept subject")

        async with new_client() as s:
            res = await s.call_tool(
                "post_to_thread",
                {"thread_id": tid, "content": "plain post", "from_agent": "alpha", "rename_to": ""},
            )
        assert res.is_error is False, _error_text(res)
        assert _payload(res).get("error") != "VALIDATION_ERROR", _payload(res)
        assert await _subject(session, tid) == "kept subject"
        assert await _posted(session, tid, "plain post") is not None

    async def test_update_thread_is_the_one_rename_door(self, be9748_client):
        new_client, _tenant_key, session = be9748_client
        tid = await _create_thread(new_client, "before")

        async with new_client() as s:
            res = await s.call_tool("update_thread", {"thread_id": tid, "subject": "after"})
        assert res.is_error is False, _error_text(res)
        assert await _subject(session, tid) == "after"

    async def test_post_to_thread_schema_no_longer_advertises_rename_to(self):
        assert "rename_to" not in _tool("post_to_thread").parameters["properties"]




class TestMarkReadIsKeptAndHonest:
    async def test_mark_read_stays_on_get_thread_history_with_a_non_read_only_hint(self):
        tool = _tool("get_thread_history")
        assert "mark_read" in tool.parameters["properties"]
        assert tool.annotations.read_only_hint is False
        assert tool.annotations.destructive_hint is False
        assert _tool("mark_thread_read") is None




class TestRetiredArgumentHelper:
    async def test_any_value_switch_names_its_one_replacement(self):
        from api.endpoints.mcp_tools._retired_arguments import retired_argument_rejection

        for value in ([{"item_type": "project", "project_id": "p"}], "x", 7, {"a": 1}):
            rejection = retired_argument_rejection("save_roadmap", {"items": [], "remove": value})
            assert rejection is not None, value
            assert rejection["field"] == "remove"
            assert rejection["constraint"] == "retired_argument"
            assert "remove_roadmap_items" in rejection["message"]
            assert "Nothing was changed" in rejection["message"]

    async def test_falsy_default_dispatches_untouched(self):
        from api.endpoints.mcp_tools._retired_arguments import retired_argument_rejection

        assert retired_argument_rejection("save_roadmap", {"items": [], "remove": None}) is None
        assert retired_argument_rejection("save_roadmap", {"items": [], "remove": []}) is None
        assert retired_argument_rejection("save_roadmap", {"items": []}) is None
        assert retired_argument_rejection("post_to_thread", {"content": "c", "rename_to": ""}) is None
        assert retired_argument_rejection("post_to_thread", {"content": "c"}) is None
        assert retired_argument_rejection("post_to_thread", {"content": "c", "rename_to": "new"}) is not None
