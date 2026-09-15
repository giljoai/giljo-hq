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
from mcp.types import Implementation

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


_CLAUDE_BLOCK = "YOUR PLATFORM: CLAUDE CODE CLI"
_GENERIC_MCP_BLOCK = "ANY MCP-CONNECTED AGENT (generic_mcp)"

_CLAUDE_CODE_INFO = Implementation(name="claude-code", version="2.1.199")
_OPENCODE_INFO = Implementation(name="opencode", version="0.3.1")
_UNKNOWN_INFO = Implementation(name="totally-made-up-harness", version="9.9.9")


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

    def _client(client_info: Implementation | None = None):
        return create_connected_server_and_client_session(mcp_sdk_server.mcp, client_info=client_info)

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
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-9035b", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    return product.id


async def _seed_orchestrator(db_session, tenant_key: str, product_id: str, execution_mode: str) -> str:
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-9035b orch {uuid.uuid4().hex[:8]}",
        description=f"{execution_mode} orchestrator",
        mission="build it",
        status="active",
        staging_status="staging",
        series_number=random.randint(1, 9000),
        execution_mode=execution_mode,
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
        mission="BE-9035b orchestrator mission",
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


async def _ch3_for(client, client_info, job_id) -> str:
    async with client(client_info) as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)
    return payload["orchestrator_protocol"]["ch3_agent_spawning_rules"]




async def test_detected_claude_code_upgrades_generic_mcp_render(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_orchestrator(db_session, tenant_key, product_id, "generic_mcp")

    ch3 = await _ch3_for(client, _CLAUDE_CODE_INFO, job_id)
    assert _CLAUDE_BLOCK in ch3, "a detected claude-code session must render the Claude Code CLI spawn block"
    assert _GENERIC_MCP_BLOCK not in ch3, "detection should have replaced the generic_mcp ladder"


async def test_detected_opencode_renders_the_universal_ladder(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_orchestrator(db_session, tenant_key, product_id, "generic_mcp")

    ch3 = await _ch3_for(client, _OPENCODE_INFO, job_id)
    assert _GENERIC_MCP_BLOCK in ch3, "opencode has no dedicated block -> the universal ladder must render"
    assert _CLAUDE_BLOCK not in ch3, "a non-claude harness must never borrow the claude render"


async def test_no_client_info_is_the_generic_floor(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_orchestrator(db_session, tenant_key, product_id, "generic_mcp")

    ch3 = await _ch3_for(client, None, job_id)
    assert _GENERIC_MCP_BLOCK in ch3
    assert _CLAUDE_BLOCK not in ch3


async def test_detection_never_downgrades_a_declared_cli(mcp_client):
    client, tenant_key, db_session = mcp_client
    product_id = await _seed_org_product(db_session, tenant_key)
    job_id = await _seed_orchestrator(db_session, tenant_key, product_id, "claude_code_cli")

    ch3 = await _ch3_for(client, _UNKNOWN_INFO, job_id)
    assert _CLAUDE_BLOCK in ch3, "a declared claude project must keep its render under an unrecognized client"
