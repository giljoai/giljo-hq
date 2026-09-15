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
from giljo_mcp.models.comm import VALID_SELF_REPORTED_STATUSES
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
    block = res.content[0]
    text = getattr(block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {block!r}")
    return json.loads(text)


def _error_text(res) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in res.content)


def _outcome(res) -> str:
    if res.is_error:
        return f"isError: {_error_text(res)[:400]}"
    return f"ok: {json.dumps(_payload(res))[:400]}"


@pytest_asyncio.fixture
async def mcp_env(db_manager, db_session, monkeypatch):
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
    user = User(id=str(uuid.uuid4()), tenant_key=tenant_key, username=f"operator_{suffix}")
    db_session.add(user)
    await db_session.flush()
    with tenant_session_context(db_session, tenant_key):
        await ensure_default_types_seeded(db_session, tenant_key)
    await db_session.commit()

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session)
    state.tool_accessor = accessor

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: user.id)

    def _new_client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _new_client, tenant_key, user.id
    finally:
        async with db_manager.get_session_async() as cleanup:
            await cleanup.execute(delete(TaxonomyType).where(TaxonomyType.tenant_key == tenant_key))
            await cleanup.commit()
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _thread_with_headless_agent(new_client, agent_id: str) -> str:
    async with new_client() as s:
        res = await s.call_tool("create_thread", {"subject": "BE-9475", "creator_id": "user-operator"})
        assert res.is_error is False, _error_text(res)
        tid = _payload(res)["thread_id"]
        joined = await s.call_tool("join_thread", {"thread_id": tid, "agent_id": agent_id, "display_name": "Lane A"})
        assert joined.is_error is False, _error_text(joined)
    return tid


async def _served_participant(new_client, thread_id: str, agent_id: str) -> dict:
    async with new_client() as s:
        res = await s.call_tool("get_participant_liveness", {"thread_id": thread_id})
    assert res.is_error is False, _error_text(res)
    return next(p for p in _payload(res)["participants"] if p["participant_id"] == agent_id)


async def _seed_execution(db_session, tenant_key: str, agent_id: str, status: str) -> None:
    with tenant_session_context(db_session, tenant_key):
        job = AgentJob(job_id=str(uuid.uuid4()), tenant_key=tenant_key, job_type="implementer")
        db_session.add(job)
        await db_session.flush()
        db_session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=agent_id,
                job_id=job.job_id,
                tenant_key=tenant_key,
                agent_display_name=f"display-{agent_id}",
                status=status,
                started_at=datetime.now(UTC),
            )
        )
        await db_session.flush()
    await db_session.commit()


async def _enroll_without_activity(db_session, tenant_key: str, thread_id: str, agent_id: str) -> None:
    from giljo_mcp.repositories.comm_thread_repository import CommThreadRepository

    with tenant_session_context(db_session, tenant_key):
        await CommThreadRepository().add_participant(
            db_session,
            tenant_key,
            thread_id,
            participant_id=agent_id,
            participant_type="agent",
            display_name="Rostered",
            role="auto-enrolled",
        )
    await db_session.commit()


async def _message_count(db_session, thread_id: str) -> int:
    return (
        await db_session.execute(select(func.count()).select_from(Message).where(Message.thread_id == thread_id))
    ).scalar_one()




async def test_control_execution_status_is_served_through_the_transport(mcp_env, db_session):
    new_client, tenant_key, _user_id = mcp_env
    agent_id = "agent-with-execution"
    tid = await _thread_with_headless_agent(new_client, agent_id)
    await _seed_execution(db_session, tenant_key, agent_id, "working")

    served = await _served_participant(new_client, tid, agent_id)
    assert served["status"] == "working"




async def test_headless_agent_can_report_working_via_post_to_thread(mcp_env, db_session):
    new_client, _tenant_key, _user_id = mcp_env
    agent_id = "E97-headless-lane"
    tid = await _thread_with_headless_agent(new_client, agent_id)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "starting the migration", "from_agent": agent_id, "my_status": "working"},
        )
    post_outcome = _outcome(res)

    served = await _served_participant(new_client, tid, agent_id)
    assert served["status"] == "working", (
        f"a headless participant that declared my_status='working' is served "
        f"status={served['status']!r} -- it has no execution row, so the dot stays "
        f"'Monitoring' no matter what it does. post_to_thread outcome: {post_outcome}"
    )


async def test_self_reported_status_is_refused_when_not_in_the_locked_vocabulary(mcp_env, db_session):
    new_client, _tenant_key, _user_id = mcp_env
    agent_id = "E97-bad-status"
    tid = await _thread_with_headless_agent(new_client, agent_id)

    async with new_client() as s:
        res = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "nope", "from_agent": agent_id, "my_status": "grinding"},
        )

    assert res.is_error is False, f"must be a BE-6081 domain rejection, not a transport error: {_error_text(res)}"
    payload = _payload(res)
    assert payload["success"] is False
    assert payload["error"] == "INVALID_MY_STATUS"
    for valid in ("working", "waiting", "blocked", "idle", "sleeping", "complete"):
        assert valid in payload["message"], f"the rejection must name {valid!r} so the caller can self-correct"
    assert "grinding" in payload["message"]
    assert await _message_count(db_session, tid) == 0, "a refused status must not persist the post"

    served = await _served_participant(new_client, tid, agent_id)
    assert served["status"] is None, "a refused status must never reach the participant row"




async def test_execution_status_wins_over_self_reported_status(mcp_env, db_session):
    new_client, tenant_key, _user_id = mcp_env
    agent_id = "agent-both-sources"
    tid = await _thread_with_headless_agent(new_client, agent_id)
    await _seed_execution(db_session, tenant_key, agent_id, "complete")

    async with new_client() as s:
        await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "I say I am working", "from_agent": agent_id, "my_status": "working"},
        )

    served = await _served_participant(new_client, tid, agent_id)
    assert served["status"] == "complete", "the execution row must win whenever one exists"


async def test_execution_status_outside_the_locked_six_still_serves_untouched(mcp_env, db_session):
    new_client, tenant_key, _user_id = mcp_env
    agent_id = "agent-closed-execution"
    tid = await _thread_with_headless_agent(new_client, agent_id)
    await _seed_execution(db_session, tenant_key, agent_id, "closed")

    assert "closed" not in VALID_SELF_REPORTED_STATUSES, "premise of this test: 'closed' is not self-awardable"

    served = await _served_participant(new_client, tid, agent_id)
    assert served["status"] == "closed", "an execution status outside the write allowlist must still be served"


async def test_control_no_status_cases_are_unchanged(mcp_env, db_session):
    new_client, tenant_key, _user_id = mcp_env
    silent_id = "agent-never-checked-in"
    poster_id = "agent-posts-no-status"
    tid = await _thread_with_headless_agent(new_client, poster_id)
    await _enroll_without_activity(db_session, tenant_key, tid, silent_id)

    async with new_client() as s:
        posted = await s.call_tool(
            "post_to_thread",
            {"thread_id": tid, "content": "here, saying nothing about myself", "from_agent": poster_id},
        )
        assert posted.is_error is False, _error_text(posted)

    never = await _served_participant(new_client, tid, silent_id)
    assert never["status"] is None
    assert never["last_seen_at"] is None, "never checked in must stay a hollow ring, not a filled idle dot"

    poster = await _served_participant(new_client, tid, poster_id)
    assert poster["status"] is None, "posting without a status must not invent one"
    assert poster["last_seen_at"] is not None
