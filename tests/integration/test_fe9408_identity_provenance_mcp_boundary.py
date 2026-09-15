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
from giljo_mcp.system_prompts.service import SystemPromptService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio

TENANT_TEXT = "TENANT-WIDE orchestrator seed for FE-9408."
PRODUCT_TEXT = "PRODUCT-SCOPED orchestrator seed for FE-9408."


def _payload(result) -> dict:
    if getattr(result, "structuredContent", None):
        return result.structured_content
    return json.loads(_raw_text(result))


def _raw_text(result) -> str:
    first = result.content[0]
    text = getattr(first, "text", None)
    if text is None:  # pragma: no cover - defensive
        raise AssertionError(f"unexpected content block: {first!r}")
    return text


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
        yield _client, tenant_key, db_session, db_manager
    finally:
        state.tool_accessor = prior_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager




async def _seed_org_product(db_session, tenant_key: str) -> tuple[str, str]:
    suffix = uuid.uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="fe-9408", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    return product.id, product.name


async def _seed_project(db_session, tenant_key: str, product_id: str, *, implementation_launched: bool) -> str:
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product_id,
        name=f"FE-9408 {uuid.uuid4().hex[:8]}",
        description="identity provenance cell",
        mission="build it",
        status="active",
        staging_status="staging_complete" if implementation_launched else "staging",
        series_number=random.randint(1, 9000),
        execution_mode="multi_terminal",
        implementation_launched_at=now if implementation_launched else None,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return project.id


async def _seed_orchestrator_job(db_session, tenant_key: str, project_id: str) -> str:
    now = datetime.now(UTC)
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type="orchestrator",
        mission="FE-9408 mission",
        status="active",
        created_at=now,
    )
    db_session.add(job)
    await db_session.flush()
    db_session.add(
        AgentExecution(
            id=str(uuid.uuid4()),
            agent_id=str(uuid.uuid4()),
            job_id=job.job_id,
            tenant_key=tenant_key,
            agent_display_name="orchestrator",
            status="working",
            started_at=now,
        )
    )
    await db_session.commit()
    return job.job_id


async def _save_override(db_manager, db_session, tenant_key: str, content: str, product_id: str | None) -> str:
    record = await SystemPromptService(db_manager=db_manager).update_orchestrator_prompt(
        tenant_key=tenant_key,
        content=content,
        updated_by="fe9408-test",
        product_id=product_id,
        session=db_session,
    )
    await db_session.commit()
    assert record.updated_at is not None
    return record.updated_at.strftime("%Y-%m-%d")


async def _mission_payload(client, job_id: str) -> dict:
    async with client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id})
        assert result.is_error is False, _error_text(result)
        return _payload(result)


async def _staging_payload(client, job_id: str) -> dict:
    async with client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
        assert result.is_error is False, _error_text(result)
        return _payload(result)




async def test_mission_tenant_scope_names_the_tenant_wide_override(mcp_client):
    client, tenant_key, db_session, db_manager = mcp_client
    product_id, _ = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, product_id, implementation_launched=True)
    job_id = await _seed_orchestrator_job(db_session, tenant_key, project_id)
    saved = await _save_override(db_manager, db_session, tenant_key, TENANT_TEXT, product_id=None)

    payload = await _mission_payload(client, job_id)

    expected = f"identity source: tenant-wide override, saved {saved}"
    assert payload["agent_identity"] is not None
    assert expected in payload["agent_identity"]
    assert payload["identity_source"] == expected


async def test_mission_product_scope_names_the_product(mcp_client):
    client, tenant_key, db_session, db_manager = mcp_client
    product_id, product_name = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, product_id, implementation_launched=True)
    job_id = await _seed_orchestrator_job(db_session, tenant_key, project_id)
    await _save_override(db_manager, db_session, tenant_key, TENANT_TEXT, product_id=None)
    saved = await _save_override(db_manager, db_session, tenant_key, PRODUCT_TEXT, product_id=product_id)

    payload = await _mission_payload(client, job_id)

    expected = f"identity source: product override ({product_name}), saved {saved}"
    assert expected in payload["agent_identity"]
    assert payload["identity_source"] == expected


async def test_mission_default_scope_says_built_in(mcp_client):
    client, tenant_key, db_session, _db_manager = mcp_client
    product_id, _ = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, product_id, implementation_launched=True)
    job_id = await _seed_orchestrator_job(db_session, tenant_key, project_id)

    payload = await _mission_payload(client, job_id)

    expected = "identity source: built-in default"
    assert expected in payload["agent_identity"]
    assert payload["identity_source"] == expected
    assert "override" not in payload["identity_source"]




async def test_staging_tenant_scope_names_the_tenant_wide_override(mcp_client):
    client, tenant_key, db_session, db_manager = mcp_client
    product_id, _ = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, product_id, implementation_launched=False)
    job_id = await _seed_orchestrator_job(db_session, tenant_key, project_id)
    saved = await _save_override(db_manager, db_session, tenant_key, TENANT_TEXT, product_id=None)

    payload = await _staging_payload(client, job_id)

    expected = f"identity source: tenant-wide override, saved {saved}"
    assert expected in payload["orchestrator_identity"]
    assert payload["identity"]["identity_source"] == expected


async def test_staging_product_scope_names_the_product(mcp_client):
    client, tenant_key, db_session, db_manager = mcp_client
    product_id, product_name = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, product_id, implementation_launched=False)
    job_id = await _seed_orchestrator_job(db_session, tenant_key, project_id)
    await _save_override(db_manager, db_session, tenant_key, TENANT_TEXT, product_id=None)
    saved = await _save_override(db_manager, db_session, tenant_key, PRODUCT_TEXT, product_id=product_id)

    payload = await _staging_payload(client, job_id)

    expected = f"identity source: product override ({product_name}), saved {saved}"
    assert expected in payload["orchestrator_identity"]
    assert payload["identity"]["identity_source"] == expected
    assert payload["identity"]["product_name"] == product_name


async def test_staging_default_scope_says_built_in(mcp_client):
    client, tenant_key, db_session, _db_manager = mcp_client
    product_id, _ = await _seed_org_product(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, product_id, implementation_launched=False)
    job_id = await _seed_orchestrator_job(db_session, tenant_key, project_id)

    payload = await _staging_payload(client, job_id)

    expected = "identity source: built-in default"
    assert expected in payload["orchestrator_identity"]
    assert payload["identity"]["identity_source"] == expected
