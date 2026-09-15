# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


_HEADER = "ANY MCP-CONNECTED AGENT (generic_mcp)"
_PREFERRED_TERMINAL_OPTION = "OPTION A — ONE TERMINAL PER AGENT"
_PREFERRED_SUBAGENT_OPTION = "OPTION B — IN-PROCESS SUBAGENT"
_PREFERRED_OPENCODE_LINE = 'cmd /k opencode --prompt "<prompt>"'
_PREFERRED_PATH_NOTE = "the cmd /k wrapper (NOT pwsh -NoExit) so opencode.cmd resolves from PATH."
_PREFERRED_TASK_TOOL = "a Task tool"
_IF_YOU_CANNOT = "[IF YOU CANNOT DO THE ABOVE]"
_SELF_ADOPT = "SELF-ADOPT"
_GRANTED = "GRANTED by your choice"
_DELEGATE_FIRST = "DELEGATE FIRST"
_VERIFY_MANDATORY = "using it is MANDATORY"
_SUBAGENT_MODE_WORD = "subagent mode"
_OLD_GENERIC_MODE_WORD = "generic_mcp mode"
_FLOOR = "[FLOOR]"
_SELF_ADOPT_ALL_JOBS = "SELF-ADOPT the queued jobs"
_CHAT_PLANNING_ONLY = "CANNOT self-adopt a CODE job"
_CHAT_LABEL = "[YOUR PATH — Chat]"
_DEFAULT_LABEL = "[YOUR PATH — Generic MCP]"


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return json.loads(text)


def _error_text(result) -> str:
    return "\n".join(b.text for b in result.content if getattr(b, "text", None))




@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior_accessor = state.tool_accessor
    prior_tenant_manager = state.tenant_manager
    prior_db_manager = state.db_manager

    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager

    tenant_key = TenantManager.generate_tenant_key()
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key, db_session
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def _seed_org_product(db_session, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-9013", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    return product.id


async def _seed_generic_mcp_orchestrator(db_session, tenant_key: str, product_id: str) -> str:
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-9013 orch {uuid.uuid4().hex[:8]}",
        description="generic_mcp orchestrator",
        mission="build it",
        status="active",
        staging_status="staging",
        series_number=random.randint(1, 9000),
        execution_mode="generic_mcp",
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="orchestrator",
        mission="BE-9013 orchestrator mission",
        status="active",
        created_at=now,
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="orchestrator",
        status="working",
        started_at=now,
    )
    db_session.add(execution)
    await db_session.commit()
    return job.job_id


async def _seed_generic_mcp_worker(db_session, tenant_key: str, product_id: str, project_id: str) -> str:
    now = datetime.now(UTC)
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="implementer",
        mission=f"BE-9013 worker mission {uuid.uuid4().hex[:6]}",
        status="active",
        created_at=now,
    )
    db_session.add(job)
    await db_session.flush()
    execution = AgentExecution(
        id=str(uuid.uuid4()),
        agent_id=str(uuid.uuid4()),
        job_id=job.job_id,
        tenant_key=tenant_key,
        agent_display_name="implementer",
        status="waiting",
        started_at=now,
    )
    db_session.add(execution)
    await db_session.flush()
    return job.job_id




async def test_generic_mcp_staging_renders_spawn_block_and_self_adopt_rung(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_generic_mcp_orchestrator(db_session, tenant_key, product_id)

    async with client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    ch3 = payload["orchestrator_protocol"]["ch3_agent_spawning_rules"]
    assert _HEADER in ch3
    assert _PREFERRED_TERMINAL_OPTION in ch3
    assert _PREFERRED_SUBAGENT_OPTION in ch3
    assert _PREFERRED_OPENCODE_LINE in ch3, "the literal opencode Windows launch line must render"
    assert _PREFERRED_PATH_NOTE in ch3, "the cmd /k (not pwsh -NoExit) PATH note must render"
    assert _PREFERRED_TASK_TOOL in ch3
    assert _DELEGATE_FIRST in ch3, "PREFERRED must lead with the DELEGATE FIRST banner"
    assert _IF_YOU_CANNOT in ch3
    assert _SELF_ADOPT in ch3
    assert _SELF_ADOPT_ALL_JOBS in ch3, "capable session's self-adopt must cover ALL queued jobs"
    assert _GRANTED in ch3, "self-adopt must be worded as a granted permission, not an ambient default"
    assert _VERIFY_MANDATORY in ch3, "self-adopt must be gated behind a verify-first MANDATORY rung"
    assert _SUBAGENT_MODE_WORD in ch3, "permission is worded as the subagent-mode choice"
    assert _OLD_GENERIC_MODE_WORD not in ch3, "permission wording moved off 'generic_mcp mode'"
    assert "get_job_mission" in ch3 and "complete_job" in ch3
    assert _FLOOR in ch3
    assert _DEFAULT_LABEL in ch3
    assert _CHAT_PLANNING_ONLY not in ch3


async def test_generic_mcp_chat_harness_tunes_self_adopt_to_planning_only(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_generic_mcp_orchestrator(db_session, tenant_key, product_id)

    async with client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id, "harness": "chat"})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    ch3 = payload["orchestrator_protocol"]["ch3_agent_spawning_rules"]
    assert _CHAT_LABEL in ch3, "the resolved chat preset label must reach the ladder header"
    assert _CHAT_PLANNING_ONLY in ch3, "chat render must exclude code jobs from self-adopt"
    assert _SELF_ADOPT in ch3 and _GRANTED in ch3, "self-adopt stays reachable (planning/PM) on chat"
    assert _DELEGATE_FIRST in ch3, "the DELEGATE FIRST banner leads the chat render too"
    assert _SUBAGENT_MODE_WORD in ch3, "chat self-adopt is granted by the subagent-mode choice"
    assert _OLD_GENERIC_MODE_WORD not in ch3, "permission wording moved off 'generic_mcp mode'"
    assert _FLOOR in ch3
    assert _SELF_ADOPT_ALL_JOBS not in ch3


@pytest.mark.parametrize("harness", ["", "not_a_real_harness"])
async def test_generic_mcp_default_and_garbage_harness_render_capable_self_adopt(mcp_client, harness):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_generic_mcp_orchestrator(db_session, tenant_key, product_id)

    async with client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id, "harness": harness})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    ch3 = payload["orchestrator_protocol"]["ch3_agent_spawning_rules"]
    assert _SELF_ADOPT_ALL_JOBS in ch3, f"harness={harness!r} must render the capable self-adopt rung"
    assert _CHAT_PLANNING_ONLY not in ch3, f"harness={harness!r} must NOT render the chat-only exclusion"




async def test_generic_mcp_two_job_self_adopt_sequence_closes_out(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)

    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-9013 selfadopt {uuid.uuid4().hex[:8]}",
        description="generic_mcp self-adopt sequence",
        mission="ship two",
        status="active",
        series_number=random.randint(1, 9000),
        execution_mode="generic_mcp",
        staging_status="staging_complete",
        implementation_launched_at=now,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()

    job1 = await _seed_generic_mcp_worker(db_session, tenant_key, product_id, project.id)
    job2 = await _seed_generic_mcp_worker(db_session, tenant_key, product_id, project.id)
    await db_session.commit()

    async with client() as session:
        m1 = await session.call_tool("get_job_mission", {"job_id": job1})
        assert m1.is_error is False, _error_text(m1)
        assert _payload(m1).get("blocked") in (False, None), _payload(m1)

        c1 = await session.call_tool(
            "complete_job",
            {
                "job_id": job1,
                "result": {"summary": "job 1 self-adopted and done"},
                "acknowledge_messages_on_complete": True,
            },
        )
        assert c1.is_error is False, _error_text(c1)

        m2 = await session.call_tool("get_job_mission", {"job_id": job2})
        assert m2.is_error is False, _error_text(m2)
        assert _payload(m2).get("blocked") in (False, None), _payload(m2)

        c2 = await session.call_tool(
            "complete_job",
            {
                "job_id": job2,
                "result": {"summary": "job 2 self-adopted and done"},
                "acknowledge_messages_on_complete": True,
            },
        )
        assert c2.is_error is False, _error_text(c2)

    from sqlalchemy import select

    for jid in (job1, job2):
        rows = (
            (await db_session.execute(select(AgentExecution.status).where(AgentExecution.job_id == jid)))
            .scalars()
            .all()
        )
        assert "complete" in rows, f"job {jid} must close out (self-adopt sequence), got {rows!r}"
