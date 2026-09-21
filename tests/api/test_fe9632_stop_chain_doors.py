# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import inspect
import secrets
import uuid
from datetime import UTC, datetime

import bcrypt
import pytest
from httpx import AsyncClient
from sqlalchemy import select

from giljo_mcp.auth.jwt_manager import JWTManager
from giljo_mcp.domain.project_status import ProjectStatus
from giljo_mcp.models import Product, Project, User
from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.sequence_runs import SequenceRun
from giljo_mcp.tenant import TenantManager
from giljo_mcp.tools.tool_accessor import _chain_tools


_TEST_CSRF_TOKEN = secrets.token_urlsafe(32)


async def _seed_chain(db_manager) -> dict:
    async with db_manager.get_session_async() as session:
        suffix = uuid.uuid4().hex[:8]
        tenant_key = TenantManager.generate_tenant_key()

        org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
        session.add(org)
        await session.flush()

        password_hash = bcrypt.hashpw(b"test_password", bcrypt.gensalt()).decode("utf-8")
        user = User(
            username=f"user_{suffix}",
            email=f"user_{suffix}@example.com",
            password_hash=password_hash,
            tenant_key=tenant_key,
            role="developer",
            org_id=org.id,
        )
        session.add(user)
        await session.flush()

        product = Product(
            id=str(uuid.uuid4()),
            name=f"Product {suffix}",
            description="stop-chain door test product",
            tenant_key=tenant_key,
            is_active=True,
            is_default=True,
        )
        session.add(product)
        await session.flush()

        pids = [str(uuid.uuid4()) for _ in range(3)]
        for i, pid in enumerate(pids):
            session.add(
                Project(
                    id=pid,
                    tenant_key=tenant_key,
                    product_id=product.id,
                    name=f"P{i + 1}",
                    description="desc",
                    mission="mission",
                    status=ProjectStatus.COMPLETED if i == 0 else ProjectStatus.ACTIVE,
                    staging_status="staging_complete",
                    implementation_launched_at=datetime.now(UTC) if i <= 1 else None,
                    series_number=i + 1,
                )
            )
        job_id = str(uuid.uuid4())
        session.add(
            AgentJob(
                job_id=job_id,
                job_type="orchestrator",
                tenant_key=tenant_key,
                project_id=pids[1],
                mission="orchestrator mission",
                status="active",
            )
        )
        session.add(
            AgentExecution(
                id=str(uuid.uuid4()),
                agent_id=str(uuid.uuid4()),
                job_id=job_id,
                tenant_key=tenant_key,
                agent_display_name="orchestrator",
                status="working",
                working_started_at=datetime.now(UTC),
            )
        )
        run_id = str(uuid.uuid4())
        session.add(
            SequenceRun(
                id=run_id,
                tenant_key=tenant_key,
                project_ids=pids,
                resolved_order=pids,
                current_index=1,
                execution_mode="subagent",
                status="running",
                locked=True,
                project_statuses={pids[0]: "completed", pids[1]: "implementing", pids[2]: "pending"},
            )
        )
        await session.commit()

        access = JWTManager.create_access_token(
            user_id=user.id, username=user.username, role="developer", tenant_key=tenant_key
        )
        headers = {
            "Cookie": f"access_token={access}; csrf_token={_TEST_CSRF_TOKEN}",
            "X-CSRF-Token": _TEST_CSRF_TOKEN,
        }
        return {"tenant_key": tenant_key, "run_id": run_id, "pids": pids, "headers": headers}


async def _project_statuses(db_manager, tenant_key: str) -> dict[str, ProjectStatus]:
    async with db_manager.get_session_async(tenant_key=tenant_key) as session:
        rows = (await session.execute(select(Project).where(Project.tenant_key == tenant_key))).scalars().all()
    return {str(r.id): r.status for r in rows}




@pytest.mark.asyncio
async def test_rest_stop_endpoint_stops_the_chain(api_client: AsyncClient, db_manager) -> None:
    seeded = await _seed_chain(db_manager)

    resp = await api_client.post(
        f"/api/v1/sequence-runs/{seeded['run_id']}/stop",
        headers=seeded["headers"],
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "cancelled"

    statuses = await _project_statuses(db_manager, seeded["tenant_key"])
    pids = seeded["pids"]
    assert statuses[pids[0]] == ProjectStatus.COMPLETED
    assert statuses[pids[1]] == ProjectStatus.TERMINATED
    assert statuses[pids[2]] == ProjectStatus.INACTIVE


@pytest.mark.asyncio
async def test_rest_stop_endpoint_requires_authentication(api_client: AsyncClient, db_manager) -> None:
    seeded = await _seed_chain(db_manager)

    resp = await api_client.post(f"/api/v1/sequence-runs/{seeded['run_id']}/stop")

    assert resp.status_code in (401, 403), resp.text


@pytest.mark.asyncio
async def test_rest_stop_endpoint_unknown_run_is_404(api_client: AsyncClient, db_manager) -> None:
    seeded = await _seed_chain(db_manager)

    resp = await api_client.post(
        f"/api/v1/sequence-runs/{uuid.uuid4()}/stop",
        headers=seeded["headers"],
    )

    assert resp.status_code == 404, resp.text




def test_accessor_terminate_remaining_routes_to_the_stop_writer() -> None:
    src = inspect.getsource(_chain_tools.ChainToolsMixin._chain_run_reverse_gear)

    assert "stop_chain(" in src, (
        "the terminate_remaining branch must reach SequenceRunService.stop_chain so the "
        "MCP door and the REST door share ONE writer"
    )
    assert 'release(run_id=run_id, mode="cancel"' not in src, (
        "the old release-only call must be gone, not left beside the new one — a second "
        "write path is exactly what the drift guard forbids"
    )


@pytest.mark.asyncio
async def test_accessor_door_mutates_members_like_the_rest_door(db_manager) -> None:
    seeded = await _seed_chain(db_manager)
    pids = seeded["pids"]

    from giljo_mcp.tools.tool_accessor import ToolAccessor

    accessor = ToolAccessor(db_manager=db_manager, tenant_manager=TenantManager())
    result = await accessor.start_chain_run(
        action="terminate_remaining",
        run_id=seeded["run_id"],
        tenant_key=seeded["tenant_key"],
    )

    assert result["success"] is True
    assert result["action"] == "terminate_remaining"
    assert result["run"]["status"] == "cancelled"

    statuses = await _project_statuses(db_manager, seeded["tenant_key"])
    assert statuses[pids[0]] == ProjectStatus.COMPLETED
    assert statuses[pids[1]] == ProjectStatus.TERMINATED
    assert statuses[pids[2]] == ProjectStatus.INACTIVE
