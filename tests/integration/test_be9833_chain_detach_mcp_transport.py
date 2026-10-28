# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import json
import random
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from giljo_mcp.database import tenant_isolation_bypass
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.services.sequence_run_service import SequenceRunService
from giljo_mcp.tenant import TenantManager
from tests.helpers.mcp_session_fixture import create_connected_server_and_client_session


pytestmark = pytest.mark.asyncio


def _payload(call_tool_result) -> dict:
    if getattr(call_tool_result, "structuredContent", None):
        return call_tool_result.structured_content
    return json.loads(call_tool_result.content[0].text)


def _error_text(call_tool_result) -> str:
    return "\n".join(getattr(b, "text", "") or "" for b in call_tool_result.content)


class _TenantSwitch:
    def __init__(self, value: str):
        self.value = value


@pytest_asyncio.fixture
async def mcp_client(db_manager, db_session, monkeypatch):
    from api import app_state
    from api.endpoints import mcp_sdk_server
    from api.endpoints.mcp_tools import _base
    from giljo_mcp.tools.tool_accessor import ToolAccessor

    state = app_state.state
    prior = (state.tool_accessor, state.tenant_manager, state.db_manager)
    if state.tenant_manager is None:
        state.tenant_manager = TenantManager()
    state.db_manager = db_manager
    state.tool_accessor = ToolAccessor(
        db_manager=db_manager, tenant_manager=state.tenant_manager, test_session=db_session
    )
    tenant = _TenantSwitch(TenantManager.generate_tenant_key())
    monkeypatch.setattr(_base, "_resolve_tenant", lambda ctx: tenant.value)
    monkeypatch.setattr(_base, "_resolve_user_id", lambda ctx: None)
    try:
        yield (lambda: create_connected_server_and_client_session(mcp_sdk_server.mcp)), tenant.value
    finally:
        state.tool_accessor, state.tenant_manager, state.db_manager = prior
        async with db_manager.get_session_async() as session:
            with tenant_isolation_bypass(session, reason="test teardown: wipe sequence_runs", models=(SequenceRun,)):
                await session.execute(delete(SequenceRun))
            await session.commit()


async def _seed_running_chain(db_session, tenant_key: str) -> dict:
    suffix = uuid4().hex[:8]
    db_session.add(Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True))
    product = Product(
        id=str(uuid4()), name=f"Product {suffix}", description="x", tenant_key=tenant_key, is_active=False
    )
    db_session.add(product)
    await db_session.flush()
    ids = []
    for status in ("completed", "active"):
        project = Project(
            id=str(uuid4()),
            tenant_key=tenant_key,
            product_id=product.id,
            name=f"Member {status} {suffix}",
            description="x",
            mission="x",
            status=status,
            execution_mode="claude_code_cli",
            series_number=random.randint(1, 9000),
        )
        db_session.add(project)
        ids.append(project.id)
    await db_session.flush()
    run_svc = SequenceRunService(db_manager=None, tenant_manager=TenantManager(), session=db_session)
    run = await run_svc.create(
        project_ids=ids, resolved_order=ids, execution_mode="claude_code_cli", tenant_key=tenant_key
    )
    await run_svc.update(
        run_id=run["id"],
        tenant_key=tenant_key,
        status="running",
        current_index=1,
        project_statuses={ids[0]: "completed", ids[1]: "implementing"},
    )
    await db_session.commit()
    return {"run_id": run["id"], "tail": ids[1], "run_svc": run_svc}


async def test_parking_the_tail_member_over_mcp_detaches_it_from_the_running_run(mcp_client, db_session):
    new_client, tenant_key = mcp_client
    seed = await _seed_running_chain(db_session, tenant_key)

    async with new_client() as session:
        result = await session.call_tool("update_project", {"project_id": seed["tail"], "status": "parked"})
        assert result.is_error is False, _error_text(result)

        run = await seed["run_svc"].get(run_id=seed["run_id"], tenant_key=tenant_key)
        assert run["project_statuses"][seed["tail"]] == "detached"
        assert run["status"] == "running"

        workflow = await session.call_tool("get_workflow_status", {"project_id": seed["tail"]})
        assert workflow.is_error is False, _error_text(workflow)
        assert _payload(workflow)["ready_to_advance"] is True
