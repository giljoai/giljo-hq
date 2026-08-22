# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary test: a filtered ``mark_read`` drain reports over the wire
what it actually changed, and the COMPLETION_BLOCKED guidance names a call that works.

The bug was only ever visible to an agent holding the tool result. It called
``get_thread_history(mark_read=true, action_required_only=true)``, read
``marked_read: 2``, called it again, read ``marked_read: 2`` again, and concluded the
server was discarding its acknowledgements. The count was the thing lying — the acks
were real — and the count is shaped at this boundary, so the regression belongs here
as well as at the service layer (CLAUDE.md / BE-5042).

Over the wire:
- a repeated filtered drain reports ``marked_read: 0`` and ``cursor_advanced: false``,
  with a note naming the unfiltered call that advances the cursor;
- the filtered drain nevertheless clears the completion gate, so ``complete_job``
  succeeds;
- the COMPLETION_BLOCKED rejection names the THREAD the blocking posts are on (the
  gate is project-scoped while the drain is thread-scoped, so "that job's coordination
  thread" was not enough to act on) and tells the caller to read it unfiltered.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

SENDER = "sender-orch"  # distinct author so the post never self-excludes the recipient


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
async def markread_mcp_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key, job_id, agent_id, project_id)``.

    Mirrors the BE-9108 gate fixture: tenant scaffolding plus product -> project ->
    orchestrator AgentJob + working AgentExecution, with the ToolAccessor threaded onto
    the rolled-back test session so every tool write stays inside the transaction.
    """
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_tool_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid.uuid4().hex[:8]

    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    user = User(id=str(uuid.uuid4()), tenant_key=tenant_key, username=f"patrik_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)

    product = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name="filtered mark_read boundary product",
        description="filtered mark_read cursor honesty",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="filtered mark_read boundary project",
        description="filtered mark_read cursor honesty",
        mission="prove the wire response reports only what changed",
        status="active",
        created_at=datetime.now(UTC),
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.flush()
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="orchestrate the filtered mark_read boundary test",
        status="active",
    )
    db_session.add(job)
    execution = AgentExecution(
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        messages_sent_count=0,
        messages_waiting_count=0,
        messages_read_count=0,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    db_session.add(execution)
    await db_session.commit()
    await db_session.refresh(job)
    await db_session.refresh(execution)

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, job.job_id, execution.agent_id, project.id
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _call(new_client, tool, args):
    async with new_client() as s:
        return await s.call_tool(tool, args)


async def _seed_thread(new_client, project_id: str, agent_id: str) -> tuple[str, list[str]]:
    """Project thread with interleaved informational + action-required posts."""
    thread = _payload(
        await _call(new_client, "create_thread", {"subject": "coord", "project_id": project_id, "creator_id": SENDER})
    )
    tid = thread["thread_id"]
    join = await _call(new_client, "join_thread", {"thread_id": tid, "agent_id": agent_id})
    assert join.is_error is False, _error_text(join)

    action_required: list[str] = []
    for index in range(4):
        needs_action = index % 2 == 1
        post = await _call(
            new_client,
            "post_to_thread",
            {
                "thread_id": tid,
                "content": f"post {index}",
                "from_agent": SENDER,
                "to_participant": agent_id,
                "requires_action": needs_action,
            },
        )
        assert post.is_error is False, _error_text(post)
        if needs_action:
            action_required.append(_payload(post)["message_id"])
    return tid, action_required


def _filtered_drain_args(tid: str, agent_id: str) -> dict:
    return {
        "thread_id": tid,
        "as_participant": agent_id,
        "unread_only": True,
        "mark_read": True,
        "action_required_only": True,
    }


async def test_repeated_filtered_drain_reports_no_new_acks_over_the_wire(markread_mcp_client):
    new_client, _tenant_key, _job_id, agent_id, project_id = markread_mcp_client
    tid, action_required = await _seed_thread(new_client, project_id, agent_id)
    args = _filtered_drain_args(tid, agent_id)

    first = _payload(await _call(new_client, "get_thread_history", args))
    assert first["marked_read"] == len(action_required)
    assert first["cursor_advanced"] is False
    assert "unread_only" in first["mark_read_note"]

    # Same posts come back (the cursor is deliberately unmoved) — but nothing new was
    # acknowledged, so the count the agent reads must be 0, not a repeated 2.
    second = _payload(await _call(new_client, "get_thread_history", args))
    assert second["count"] == len(action_required)
    assert second["marked_read"] == 0
    assert second["cursor_advanced"] is False


async def test_filtered_drain_unblocks_complete_job_over_the_wire(markread_mcp_client):
    new_client, _tenant_key, job_id, agent_id, project_id = markread_mcp_client
    tid, _action_required = await _seed_thread(new_client, project_id, agent_id)

    blocked = await _call(new_client, "complete_job", {"job_id": job_id, "result": {"summary": "should block"}})
    assert blocked.is_error is True
    assert "COMPLETION_BLOCKED" in _error_text(blocked)

    drained = await _call(new_client, "get_thread_history", _filtered_drain_args(tid, agent_id))
    assert drained.is_error is False, _error_text(drained)
    assert _payload(drained)["marked_read"] >= 1

    done = await _call(new_client, "complete_job", {"job_id": job_id, "result": {"summary": "closed"}})
    assert done.is_error is False, _error_text(done)
    assert _payload(done).get("status") == "success"


async def test_completion_blocked_guidance_names_the_thread_and_the_unfiltered_read(markread_mcp_client):
    new_client, _tenant_key, job_id, agent_id, project_id = markread_mcp_client
    tid, _action_required = await _seed_thread(new_client, project_id, agent_id)

    blocked = await _call(new_client, "complete_job", {"job_id": job_id, "result": {"summary": "should block"}})
    assert blocked.is_error is True
    text = _error_text(blocked)

    # The gate is project-scoped, the drain is thread-scoped: without the thread id the
    # agent has message ids it cannot act on, and may drain a thread they are not on.
    assert tid in text, "COMPLETION_BLOCKED must name the thread carrying the blocking posts"
    # And it must not send the caller back to a narrowed read, which acks what it
    # returns but leaves unread_only re-serving the same posts forever.
    assert "action_required_only" in text
