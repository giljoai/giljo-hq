# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from giljo_mcp.models.agent_identity import AgentExecution, AgentJob
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_lifecycle_service import ProjectLifecycleService
from giljo_mcp.tenant import TenantManager
from tests.helpers.test_db_helper import purge_tenant_rows


pytestmark = pytest.mark.asyncio


def _mock_ws() -> MagicMock:
    ws = MagicMock()
    ws.broadcast_to_tenant = AsyncMock()
    ws.broadcast_project_update = AsyncMock()
    return ws


def _status_changed_events(mock_ws: MagicMock) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for call in mock_ws.broadcast_to_tenant.await_args_list:
        kwargs = call.kwargs
        if kwargs.get("event_type") == "agent:status_changed":
            events.append(kwargs.get("data") or {})
    return events


async def _seed_execution(
    session: AsyncSession, tenant_key: str, project_id: str, *, display_name: str, status: str
) -> tuple[str, str]:
    job_id = str(uuid.uuid4())
    job = AgentJob(
        job_id=job_id,
        tenant_key=tenant_key,
        project_id=project_id,
        job_type=display_name,
        mission="BE-9273 fixture agent",
        status="active",
        created_at=datetime.now(UTC),
    )
    session.add(job)
    execution = AgentExecution(
        agent_id=str(uuid.uuid4()),
        job_id=job_id,
        tenant_key=tenant_key,
        agent_display_name=display_name,
        agent_name=display_name,
        status=status,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )
    session.add(execution)
    await session.flush()
    return job_id, execution.agent_id


async def test_rest_selfheal_complete_project_broadcasts_status_changed_post_commit(db_manager) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    TenantManager.set_current_tenant(tenant_key)
    try:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product = Product(
                id=str(uuid.uuid4()),
                name=f"BE-9273 Product {uuid.uuid4().hex[:8]}",
                description="BE-9273 REST self-heal closeout broadcast regression.",
                tenant_key=tenant_key,
                is_active=False,
            )
            session.add(product)
            await session.flush()

            project = Project(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                product_id=product.id,
                name="BE-9273 REST self-heal project",
                description="REST self-heal closeout WS broadcast regression.",
                mission="Prove the REST complete_project self-heal path broadcasts too.",
                status="active",
                series_number=random.randint(1, 9000),
            )
            session.add(project)
            await session.flush()

            job_id, _agent_id = await _seed_execution(
                session, tenant_key, project.id, display_name="implementer", status="working"
            )
            project_id = project.id
            await session.commit()

        mock_ws = _mock_ws()
        service = ProjectLifecycleService(
            db_manager=db_manager, tenant_manager=TenantManager(), websocket_manager=mock_ws
        )

        result = await service.complete_project(
            project_id=project_id,
            summary="BE-9273 REST self-heal force-decommission regression",
            key_outcomes=["Proved the REST self-heal path broadcasts agent:status_changed"],
            decisions_made=["Reuse broadcast_agent_status_events after our own commit"],
            tenant_key=tenant_key,
        )

        assert result.memory_updated is True

        events = _status_changed_events(mock_ws)
        assert len(events) == 1, "exactly one agent:status_changed for the force-decommissioned straggler agent"
        event = events[0]
        assert event["job_id"] == job_id
        assert event["old_status"] == "working"
        assert event["status"] == "decommissioned"
        assert event["product_id"] == product.id

        mock_ws.broadcast_project_update.assert_awaited_once()
        assert mock_ws.broadcast_project_update.await_args.kwargs["project_data"]["product_id"] == product.id
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        TenantManager.clear_current_tenant()


async def test_rest_selfheal_complete_project_no_agents_emits_nothing(db_manager) -> None:
    tenant_key = TenantManager.generate_tenant_key()
    TenantManager.set_current_tenant(tenant_key)
    try:
        async with db_manager.get_session_async(tenant_key=tenant_key) as session:
            product = Product(
                id=str(uuid.uuid4()),
                name=f"BE-9273 Product {uuid.uuid4().hex[:8]}",
                description="BE-9273 no-op regression.",
                tenant_key=tenant_key,
                is_active=False,
            )
            session.add(product)
            await session.flush()

            project = Project(
                id=str(uuid.uuid4()),
                tenant_key=tenant_key,
                product_id=product.id,
                name="BE-9273 no-agents project",
                description="No active agents to decommission.",
                mission="Prove the no-op case stays silent.",
                status="active",
                series_number=random.randint(1, 9000),
            )
            session.add(project)
            await session.flush()
            project_id = project.id
            await session.commit()

        mock_ws = _mock_ws()
        service = ProjectLifecycleService(
            db_manager=db_manager, tenant_manager=TenantManager(), websocket_manager=mock_ws
        )

        result = await service.complete_project(
            project_id=project_id,
            summary="BE-9273 no-op regression",
            key_outcomes=["No agents to decommission"],
            decisions_made=["Broadcast must stay silent"],
            tenant_key=tenant_key,
        )

        assert result.memory_updated is True
        assert _status_changed_events(mock_ws) == []
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        TenantManager.clear_current_tenant()
