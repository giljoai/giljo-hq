# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy import select

from api.endpoints.projects.lifecycle import archive_project as archive_endpoint
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_service import ProjectService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    first_block = call_tool_result.content[0]
    text = getattr(first_block, "text", None)
    if text is None:
        raise AssertionError(f"unexpected content block: {first_block!r}")
    return json.loads(text)


@pytest_asyncio.fixture
async def mcp_client(db_manager, monkeypatch):
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
    state.tool_accessor = ToolAccessor(db_manager=db_manager, tenant_manager=state.tenant_manager)

    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant_key)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)

    def _client():
        return create_connected_server_and_client_session(mcp_sdk_server.mcp)

    try:
        yield _client, tenant_key
    finally:
        state.tool_accessor = prior_tool_accessor
        state.tenant_manager = prior_tenant_manager
        state.db_manager = prior_db_manager


async def _seed_project_with_working_agent(db_manager, tenant_key: str) -> tuple[str, str]:
    product_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    job_id = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())

    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        session.add(
            Product(
                id=product_id,
                name=f"BE-9539 Product {uuid.uuid4().hex[:6]}",
                description="BE-9539 archive-respects-closeout-gate path.",
                tenant_key=tenant_key,
                is_active=True,
                product_memory={},
            )
        )
        session.add(
            Project(
                id=project_id,
                tenant_key=tenant_key,
                product_id=product_id,
                name=f"BE-9539 {uuid.uuid4().hex[:6]}",
                description="Project archived without ever closing out.",
                mission="Prove archive refuses without a closeout entry.",
                status="active",
                staging_status="staging_complete",
                series_number=random.randint(1, 9999),
            )
        )
        session.add(
            AgentJob(
                job_id=job_id,
                tenant_key=tenant_key,
                project_id=project_id,
                job_type="orchestrator",
                mission="BE-9539 fixture orchestrator",
                status="active",
                created_at=datetime.now(UTC),
            )
        )
        session.add(
            AgentExecution(
                id=execution_id,
                agent_id=str(uuid.uuid4()),
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                agent_name="orchestrator",
                status="working",
                started_at=datetime.now(UTC) - timedelta(minutes=5),
            )
        )
        await session.commit()

    return project_id, execution_id


async def _read_back_project(db_manager, tenant_key: str, project_id: str) -> Project:
    async with db_manager.get_session_async(tenant_key=tenant_key) as verify:
        return (await verify.execute(select(Project).where(Project.id == project_id))).scalar_one()


async def test_update_project_completed_without_closeout_is_blocked(mcp_client, db_manager):
    client, tenant_key = mcp_client
    project_id, _execution_id = await _seed_project_with_working_agent(db_manager, tenant_key)

    try:
        async with client() as mcp_session:
            result = await mcp_session.call_tool("update_project", {"project_id": project_id, "status": "completed"})

        assert not result.is_error, f"CLOSEOUT_BLOCKED must be a structured rejection, not isError: {result!r}"
        payload = _payload(result)
        assert payload.get("success") is False, f"archive must be refused, got: {payload!r}"
        assert payload.get("error") == "CLOSEOUT_BLOCKED", f"expected CLOSEOUT_BLOCKED, got: {payload!r}"
        assert payload.get("blockers"), "the rejection must name blockers, mirroring write_project_closeout's shape"

        project = await _read_back_project(db_manager, tenant_key, project_id)
        assert project.status == "active", "the project must NOT have archived -- no closeout, no silent completion"
        assert project.closeout_executed_at is None
    finally:
        await purge_tenant_rows(db_manager, tenant_key)


async def test_update_project_completed_with_explicit_override_still_archives(mcp_client, db_manager):
    client, tenant_key = mcp_client
    project_id, _execution_id = await _seed_project_with_working_agent(db_manager, tenant_key)

    try:
        async with client() as mcp_session:
            result = await mcp_session.call_tool(
                "update_project", {"project_id": project_id, "status": "completed", "force": True}
            )

        assert not result.is_error, f"forced archive must succeed: {result!r}"
        payload = _payload(result)
        assert payload.get("success") is True, f"expected success with force=true, got: {payload!r}"

        project = await _read_back_project(db_manager, tenant_key, project_id)
        assert project.status == "completed", "force=true must still run the archive lifecycle"
    finally:
        await purge_tenant_rows(db_manager, tenant_key)


async def test_rest_archive_endpoint_keeps_its_explicit_abandon_contract(db_manager):
    tenant_key = TenantManager.generate_tenant_key()
    project_id, _execution_id = await _seed_project_with_working_agent(db_manager, tenant_key)

    token = TenantManager.set_current_tenant(tenant_key)
    try:
        project_service = ProjectService(db_manager=db_manager, tenant_manager=TenantManager())
        current_user = SimpleNamespace(username="patrik", tenant_key=tenant_key)

        response = await archive_endpoint(
            project_id=project_id, current_user=current_user, project_service=project_service
        )

        assert response.status == "completed", "the dashboard Archive door must succeed with no closeout entry"

        project = await _read_back_project(db_manager, tenant_key, project_id)
        assert project.status == "completed"
        assert project.closeout_executed_at is None, "archiving through this door does not fabricate a closeout entry"
    finally:
        from giljo_mcp.tenant import current_tenant

        current_tenant.reset(token)
        await purge_tenant_rows(db_manager, tenant_key)
