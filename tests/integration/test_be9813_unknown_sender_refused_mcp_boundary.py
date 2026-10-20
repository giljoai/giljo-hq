# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from sqlalchemy import delete, func, select

from giljo_mcp.database import tenant_session_context
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.auth import User
from giljo_mcp.models.comm import CommParticipant
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.projects import TaxonomyType
from giljo_mcp.models.tasks import Message
from giljo_mcp.services.taxonomy_ops import ensure_default_types_seeded
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(res) -> dict:
    if getattr(res, "structuredContent", None):
        return res.structured_content
    return json.loads(res.content[0].text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


@pytest_asyncio.fixture
async def hub(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    suffix = uuid.uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    user = User(id=str(uuid.uuid4()), tenant_key=tenant_key, username=f"operator_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: user.id)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, user.id, db_session
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor, state.tenant_manager, state.db_manager = prior


async def _call(new_client, tool: str, args: dict):
    async with new_client() as s:
        return await s.call_tool(tool, args)


async def _thread(new_client) -> str:
    res = await _call(new_client, "create_thread", {"subject": "BE-9813 sender", "creator_id": "em"})
    assert res.is_error is False, _error_text(res)
    return _payload(res)["thread_id"]


async def _post(new_client, thread_id: str, from_agent: str) -> dict:
    res = await _call(
        new_client, "post_to_thread", {"thread_id": thread_id, "content": "hello", "from_agent": from_agent}
    )
    assert res.is_error is False, _error_text(res)
    return _payload(res)


async def _seed_execution(db_session, tenant_key: str, agent_id: str, job_id: str | None = None) -> None:
    with tenant_session_context(db_session, tenant_key):
        job = AgentJob(job_id=job_id or str(uuid.uuid4()), tenant_key=tenant_key, job_type="orchestrator")
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                job_id=job.job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                status="working",
                started_at=datetime.now(UTC),
            )
        )
        await db_session.flush()
    await db_session.commit()


async def _counts(db_session, tenant_key: str, thread_id: str, sender: str) -> tuple[int, int]:
    messages = await db_session.scalar(
        select(func.count())
        .select_from(Message)
        .where(Message.tenant_key == tenant_key, Message.thread_id == thread_id)
    )
    rows = await db_session.scalar(
        select(func.count())
        .select_from(CommParticipant)
        .where(
            CommParticipant.tenant_key == tenant_key,
            CommParticipant.thread_id == thread_id,
            CommParticipant.participant_id == sender,
        )
    )
    return messages, rows


async def test_unknown_uuid_sender_is_refused_and_nothing_is_written(hub):
    new_client, tenant_key, _user_id, db_session = hub
    tid = await _thread(new_client)
    stranger = str(uuid.uuid4())
    before = await _counts(db_session, tenant_key, tid, stranger)

    body = await _post(new_client, tid, stranger)

    assert body.get("success") is False, f"unknown sender was accepted: {body}"
    assert body["error"] == "VALIDATION_ERROR"
    assert body["field"] == "from_agent"
    assert "join_thread" in body["message"]
    assert await _counts(db_session, tenant_key, tid, stranger) == before == (before[0], 0)


async def test_execution_agent_id_from_another_tenant_is_still_unknown(hub, db_session):
    new_client, _tenant_key, _user_id, _ = hub
    tid = await _thread(new_client)
    foreign_agent = str(uuid.uuid4())
    await _seed_execution(db_session, TenantManager.generate_tenant_key(), foreign_agent)

    body = await _post(new_client, tid, foreign_agent)

    assert body.get("success") is False, body
    assert body["error"] == "VALIDATION_ERROR"


async def test_joined_uuid_sender_still_posts(hub):
    new_client, _tk, _u, _s = hub
    tid = await _thread(new_client)
    lane = str(uuid.uuid4())
    joined = await _call(new_client, "join_thread", {"thread_id": tid, "agent_id": lane, "display_name": "Lane"})
    assert joined.is_error is False, _error_text(joined)

    assert (await _post(new_client, tid, lane)).get("success") is not False


async def test_agent_execution_sender_posts_without_joining(hub):
    new_client, tenant_key, _u, db_session = hub
    tid = await _thread(new_client)
    agent_id = str(uuid.uuid4())
    await _seed_execution(db_session, tenant_key, agent_id)

    body = await _post(new_client, tid, agent_id)

    assert body.get("success") is not False, body
    assert body["from_agent_id"] == agent_id


async def test_orchestrator_job_id_sender_posts_as_the_reactivation_protocol_prescribes(hub):
    new_client, tenant_key, _u, db_session = hub
    tid = await _thread(new_client)
    job_id = str(uuid.uuid4())
    await _seed_execution(db_session, tenant_key, str(uuid.uuid4()), job_id=job_id)

    assert (await _post(new_client, tid, job_id)).get("success") is not False


async def test_operator_user_id_sender_still_posts(hub):
    new_client, _tk, user_id, _s = hub
    tid = await _thread(new_client)

    assert (await _post(new_client, tid, user_id)).get("success") is not False


@pytest.mark.parametrize("label", ["Chain Conductor", "implementer", "lane-ci1"])
async def test_server_prescribed_labels_still_post_unjoined(hub, label):
    new_client, _tk, _u, _s = hub
    tid = await _thread(new_client)

    assert (await _post(new_client, tid, label)).get("success") is not False
