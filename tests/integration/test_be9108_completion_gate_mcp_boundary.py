# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""MCP-transport boundary test for BE-9108 — the completion gate clears over the wire
once a directed ``requires_action`` post is drained via ``get_thread_history(mark_read=true)``.

CLAUDE.md / BE-5042 mandate a regression at the layer the behavior lives. This bug is
tool-visible: an agent calls ``complete_job`` (FastMCP ``@mcp.tool`` -> ``_call_tool``
-> ``JobCompletionService.complete_job``) and is rejected with COMPLETION_BLOCKED, then
follows the hint (``get_thread_history`` with ``mark_read=true``), and must be able to
complete. The regressed gate keyed on the dead ``Message.status`` column instead of the
``message_acknowledgments`` drain, so that second complete_job stayed blocked forever —
the live 2026-07-10 deadlock. Only an end-to-end transport test exercises the exact
tool sequence the orchestration hub uses.

Over the wire:
- a directed requires_action post blocks complete_job (isError, COMPLETION_BLOCKED);
- get_thread_history(mark_read=true) as the recipient drains it (writes an ack row);
- complete_job then SUCCEEDS.
"""

from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models import AgentExecution, AgentJob, Project
from giljo_mcp.models.auth import User
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import MessageAcknowledgment
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
async def gate_mcp_client(db_manager, db_session, monkeypatch):
    """Yield ``(new_client, tenant_key, db_session, job_id, agent_id, project_id)``.

    Seeds tenant scaffolding (org/user/taxonomy) plus a product -> project ->
    orchestrator AgentJob + working AgentExecution, so ``complete_job`` has a real
    target. ToolAccessor receives ``test_session`` so all tool writes land in the
    rolled-back transaction (visible to db_session, no commit)."""
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
        name="BE-9108 boundary product",
        description="ack-drain gate boundary",
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name="BE-9108 boundary project",
        description="ack-drain gate boundary",
        mission="verify complete_job clears over the wire after mark_read",
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
        mission="orchestrate boundary gate test",
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
    agent_id = execution.agent_id
    project_id = project.id

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, db_session, job.job_id, agent_id, project_id
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


async def test_complete_job_clears_after_mark_read_over_the_wire(gate_mcp_client):
    new_client, tenant_key, db_session, job_id, agent_id, project_id = gate_mcp_client

    # Sender opens a project-anchored thread; recipient (the completing agent) joins.
    thread = _payload(
        await _call(new_client, "create_thread", {"subject": "coord", "project_id": project_id, "creator_id": SENDER})
    )
    tid = thread["thread_id"]
    join = await _call(new_client, "join_thread", {"thread_id": tid, "agent_id": agent_id})
    assert join.is_error is False, _error_text(join)

    # Directed, action-required post to the recipient.
    post = await _call(
        new_client,
        "post_to_thread",
        {
            "thread_id": tid,
            "content": "please review before closeout",
            "from_agent": SENDER,
            "to_participant": agent_id,
            "requires_action": True,
        },
    )
    assert post.is_error is False, _error_text(post)
    message_id = _payload(post)["message_id"]

    # (1) complete_job is BLOCKED over the wire.
    blocked = await _call(new_client, "complete_job", {"job_id": job_id, "result": {"summary": "should block"}})
    assert blocked.is_error is True, "an undrained action-required post must block complete_job"
    assert "COMPLETION_BLOCKED" in _error_text(blocked)

    # (2) Drain via the hint's remedy: read + ack as the recipient participant.
    drained = await _call(
        new_client,
        "get_thread_history",
        {"thread_id": tid, "as_participant": agent_id, "mark_read": True},
    )
    assert drained.is_error is False, _error_text(drained)
    assert _payload(drained)["marked_read"] >= 1

    # The ack the gate reads now exists for (message_id, recipient).
    with tenant_session_context(db_session, tenant_key):
        ack_count = (
            await db_session.execute(
                select(func.count())
                .select_from(MessageAcknowledgment)
                .where(
                    MessageAcknowledgment.message_id == message_id,
                    MessageAcknowledgment.agent_id == agent_id,
                    MessageAcknowledgment.tenant_key == tenant_key,
                )
            )
        ).scalar_one()
    assert ack_count == 1

    # (3) complete_job now SUCCEEDS over the wire — the deadlock is gone.
    done = await _call(new_client, "complete_job", {"job_id": job_id, "result": {"summary": "drained and closed"}})
    assert done.is_error is False, _error_text(done)
    assert _payload(done).get("status") == "success"
