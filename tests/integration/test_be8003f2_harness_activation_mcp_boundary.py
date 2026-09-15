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

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

_FLOOR = "[FLOOR]"
_INLINE = "INLINE CONDUCTING"
_WEB_SANDBOX_LABEL = "Web Sandbox"
_SHELL_ASIDE = "ENVIRONMENT DETECTION"
_CHAT_ASIDE = "NO SHELL (chat session)"
_S1_GATED = ("wt -w 0", "gnome-terminal", "osascript", "$DISPLAY", "$WAYLAND_DISPLAY")


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
async def tenant_key() -> str:
    return TenantManager.generate_tenant_key()


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, tenant_key, monkeypatch):
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
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def _seed_product(db_session, tenant_key: str) -> str:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-8003f2", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    return product.id


async def _seed_chain_project(db_session, tenant_key: str) -> str:
    _owning_product_project = Product(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        name=f"Owning Product {uuid.uuid4().hex[:6]}",
        description="seeded",
        is_active=False,
    )
    db_session.add(_owning_product_project)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=_owning_product_project.id,
        name=f"BE-8003f2 {uuid.uuid4().hex[:8]}",
        description="chain member",
        mission="build it",
        status="active",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="claude_code_cli",
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return project.id


async def _seed_impl_worker(db_session, tenant_key: str, product_id: str) -> str:
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"BE-8003f2 worker {uuid.uuid4().hex[:8]}",
        description="worker host",
        mission="ship it",
        status="active",
        series_number=uuid.uuid4().int % 9000 + 1,
        execution_mode="multi_terminal",
        staging_status="staging_complete",
        implementation_launched_at=now,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()

    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project.id,
        job_type="implementer",
        mission="BE-8003f2 worker mission",
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
    await db_session.commit()
    return job.job_id




async def test_get_job_mission_chat_harness_renders_shell_less_worker(mcp_client, db_session, tenant_key):
    product_id = await _seed_product(db_session, tenant_key)
    job_id = await _seed_impl_worker(db_session, tenant_key, product_id)

    async with mcp_client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, "harness": "chat"})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    protocol = payload["full_protocol"]
    assert protocol, "worker mission must carry a full_protocol"
    assert _FLOOR in protocol, "chat render must carry the [FLOOR] fallback line"
    assert _CHAT_ASIDE in protocol, "chat render must carry the shell-less worker banner"
    assert _SHELL_ASIDE not in protocol, "chat render leaked the shell env-detection aside"


@pytest.mark.parametrize("harness", ["", "not_a_real_harness"])
async def test_get_job_mission_default_and_garbage_harness_degrade_to_cli(mcp_client, db_session, tenant_key, harness):
    product_id = await _seed_product(db_session, tenant_key)
    job_id = await _seed_impl_worker(db_session, tenant_key, product_id)

    async with mcp_client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id, "harness": harness})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    protocol = payload["full_protocol"]
    assert _SHELL_ASIDE in protocol, f"CLI render (harness={harness!r}) must keep the shell env-detection aside"
    assert _CHAT_ASIDE not in protocol, f"CLI render (harness={harness!r}) must NOT carry the chat banner"




async def _start_chain_and_get_conductor(session, p1: str, p2: str) -> str:
    result = await session.call_tool("link_projects", {"project_ids": [p1, p2], "execution_mode": "claude_code_cli"})
    assert result.is_error is False, _error_text(result)
    payload = _payload(result)
    assert payload["success"] is True
    return payload["conductor_job_id"]


async def test_get_staging_instructions_web_sandbox_renders_inline_conducting(mcp_client, db_session, tenant_key):
    await _seed_product(db_session, tenant_key)
    p1 = await _seed_chain_project(db_session, tenant_key)
    p2 = await _seed_chain_project(db_session, tenant_key)
    await db_session.commit()

    async with mcp_client() as session:
        conductor_job_id = await _start_chain_and_get_conductor(session, p1, p2)
        result = await session.call_tool(
            "get_staging_instructions", {"job_id": conductor_job_id, "harness": "web_sandbox"}
        )
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["status"] == "CHAIN_CONDUCTOR_STAGING"
    capability = payload["orchestrator_protocol"]["ch_capability"]
    assert _INLINE in capability, "web_sandbox conductor must render the inline-conducting capability"
    assert _FLOOR in capability, "web_sandbox conductor capability must carry the [FLOOR] line"
    assert _WEB_SANDBOX_LABEL in capability
    for marker in _S1_GATED:
        assert marker not in capability, f"web_sandbox conductor capability leaked terminal marker {marker!r}"


@pytest.mark.parametrize("harness", ["", "not_a_real_harness"])
async def test_get_staging_instructions_default_and_garbage_degrade_to_cli(mcp_client, db_session, tenant_key, harness):
    await _seed_product(db_session, tenant_key)
    p1 = await _seed_chain_project(db_session, tenant_key)
    p2 = await _seed_chain_project(db_session, tenant_key)
    await db_session.commit()

    async with mcp_client() as session:
        conductor_job_id = await _start_chain_and_get_conductor(session, p1, p2)
        result = await session.call_tool("get_staging_instructions", {"job_id": conductor_job_id, "harness": harness})
        assert result.is_error is False, _error_text(result)
        payload = _payload(result)

    assert payload["status"] == "CHAIN_CONDUCTOR_STAGING"
    capability = payload["orchestrator_protocol"]["ch_capability"]
    assert _INLINE not in capability, (
        f"CLI conductor render (harness={harness!r}) must NOT carry the inline-conducting marker"
    )
