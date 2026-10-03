# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest
import pytest_asyncio

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.settings import Settings
from giljo_mcp.services.mission_service import MissionService
from giljo_mcp.services.orchestration_service import OrchestrationService
from giljo_mcp.services.settings_service import SettingsService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


SERENA_TOOL_NAMES = (
    "find_symbol",
    "get_symbols_overview",
    "find_referencing_symbols",
    "search_for_pattern",
    "replace_symbol_body",
    "insert_after_symbol",
    "insert_before_symbol",
)

LEGACY_INTEGRATIONS = {
    "git_integration": {"enabled": False, "use_in_prompts": False},
    "serena_mcp": {"use_in_prompts": True},
}


def _assert_no_serena(text: str, where: str) -> None:
    assert "serena" not in text.lower(), f"{where} still names Serena"
    for tool in SERENA_TOOL_NAMES:
        assert tool not in text, f"{where} still lists the Serena tool {tool}"


def _raw_text(result) -> str:
    return "\n".join(block.text for block in result.content if getattr(block, "text", None))


async def _seed_legacy_settings(db_session, tenant_key: str) -> None:
    db_session.add(
        Settings(
            id=str(uuid.uuid4()),
            tenant_key=tenant_key,
            category="integrations",
            settings_data=json.loads(json.dumps(LEGACY_INTEGRATIONS)),
        )
    )
    await db_session.flush()


async def _seed_project(db_session, tenant_key: str, *, launched: bool) -> str:
    suffix = uuid.uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    await db_session.flush()
    product = Product(
        id=str(uuid.uuid4()), name=f"Product {suffix}", description="be-9720", tenant_key=tenant_key, is_active=True
    )
    db_session.add(product)
    await db_session.flush()
    now = datetime.now(UTC)
    project = Project(
        id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"BE-9720 {suffix}",
        description="integration removal cell",
        mission="build it",
        status="active",
        staging_status="staging_complete" if launched else "staging",
        series_number=random.randint(1, 9000),
        execution_mode="multi_terminal",
        implementation_launched_at=now if launched else None,
        created_at=now,
    )
    db_session.add(project)
    db_session.info["tenant_key"] = tenant_key
    await db_session.flush()
    return project.id


async def _seed_job(db_session, tenant_key: str, project_id: str, role: str) -> str:
    now = datetime.now(UTC)
    job = AgentJob(
        job_id=str(uuid.uuid4()),
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=role,
        mission="BE-9720 mission",
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
            agent_display_name=role,
            agent_name=role,
            status="working",
            started_at=now,
        )
    )
    await db_session.commit()
    return job.job_id


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




@pytest.mark.asyncio
async def test_staging_payload_over_transport_carries_no_serena(mcp_client):
    client, tenant_key, db_session = mcp_client
    await _seed_legacy_settings(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, launched=False)
    job_id = await _seed_job(db_session, tenant_key, project_id, "orchestrator")

    async with client() as session:
        result = await session.call_tool("get_staging_instructions", {"job_id": job_id})
    assert result.is_error is False, _raw_text(result)

    _assert_no_serena(_raw_text(result), "get_staging_instructions")


@pytest.mark.asyncio
@pytest.mark.parametrize("role", ["orchestrator", "implementer"])
async def test_job_mission_over_transport_carries_no_serena(mcp_client, role):
    client, tenant_key, db_session = mcp_client
    await _seed_legacy_settings(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, launched=True)
    job_id = await _seed_job(db_session, tenant_key, project_id, role)

    async with client() as session:
        result = await session.call_tool("get_job_mission", {"job_id": job_id})
    assert result.is_error is False, _raw_text(result)

    _assert_no_serena(_raw_text(result), f"get_job_mission ({role})")




@pytest.mark.asyncio
async def test_staging_service_payload_carries_no_serena(db_session):
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_legacy_settings(db_session, tenant_key)
    project_id = await _seed_project(db_session, tenant_key, launched=False)
    job_id = await _seed_job(db_session, tenant_key, project_id, "orchestrator")

    service = OrchestrationService(db_manager=MagicMock(), tenant_manager=MagicMock(), websocket_manager=MagicMock())
    service._test_session = db_session
    service._mission._test_session = db_session
    service._mission._orchestration._test_session = db_session

    result = await service._mission.get_staging_instructions(job_id=job_id, tenant_key=tenant_key)

    assert "serena_guidance" not in result
    assert "serena_mcp_enabled" not in result["integrations"]
    _assert_no_serena(json.dumps(result, default=str), "staging service payload")


@pytest.mark.parametrize("role", ["orchestrator", "implementer", "tester", "agent"])
def test_assembled_mission_carries_no_serena(role):
    tenant_key = "tenant-be9720"
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=str(uuid.uuid4()),
        mission="Do the assigned work.",
        job_type=role,
        status="active",
    )
    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=role,
        agent_name=f"{role}-1",
        status="waiting",
    )
    service = MissionService(db_manager=MagicMock(), tenant_manager=MagicMock())

    response = service._assemble_mission_context(
        job=job,
        execution=execution,
        project=None,
        agent_identity=None,
        all_project_executions=[execution],
        mission_lookup={},
        current_team_state=None,
        tenant_key=tenant_key,
        integrations=json.loads(json.dumps(LEGACY_INTEGRATIONS)),
    )

    _assert_no_serena(response.mission or "", f"assembled mission ({role})")
    _assert_no_serena(response.full_protocol or "", f"assembled protocol ({role})")




@pytest.mark.asyncio
async def test_old_settings_shape_loads_saves_and_drops_the_key(db_session):
    tenant_key = TenantManager.generate_tenant_key()
    await _seed_legacy_settings(db_session, tenant_key)
    service = SettingsService(db_session, tenant_key)

    loaded = await service.get_settings("integrations")
    assert loaded["git_integration"]["enabled"] is False

    loaded["git_integration"]["enabled"] = True
    saved = await service.update_settings("integrations", loaded)

    assert saved["git_integration"]["enabled"] is True
    assert "serena_mcp" not in saved
    assert "serena_mcp" not in await service.get_settings("integrations")
