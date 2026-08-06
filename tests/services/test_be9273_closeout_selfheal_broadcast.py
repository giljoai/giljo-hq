# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9273 item 1 -- the REST self-heal complete_project flow must broadcast
``agent:status_changed`` for any agent it force-decommissions, mirroring the
BE-9246 fix already shipped for the owns_session=True MCP-tool closeout path.

Root cause (see ``closeout_ws_broadcast.broadcast_agent_status_events``
docstring, unchanged by this fix): ``close_project_and_update_memory`` is
called from ``ProjectLifecycleService._complete_project_transaction`` with
``session=session`` (that inner call's ``owns_session`` is False from ITS
perspective, since ``_complete_project_transaction`` owns the commit), so it
must NOT broadcast from inside itself -- a broadcast there could announce a
status a rollback in the OUTER caller could still undo. Before this fix, the
outer caller never picked up the slack: the force-decommission events it
computed were simply discarded, so the REST "Complete Project" dashboard
action force-decommissioning a straggler agent left that agent's dashboard
tile stale until a manual refresh.

Fix: ``close_project_and_update_memory`` grew an optional
``decommission_events_out`` list the caller can pass to receive the raw
events; ``_complete_project_transaction`` passes one, then -- ONLY after its
own ``session.commit()`` actually lands -- broadcasts them via the SAME
``broadcast_agent_status_events`` helper BE-9246 introduced.

Failing layer: SERVICE (``ProjectLifecycleService.complete_project``), driven
end-to-end against a real committing session (mirrors
``test_be9256_lifecycle_success_check.py`` / test 5 of
``test_be9246_closeout_ws_broadcast.py``) so the commit-then-broadcast
ordering is genuinely observable -- the rollback-isolated ``db_session``
fixture cannot demonstrate a real commit.

Parallel-safe: unique tenant_key per test, real db_manager session cleaned up
via ``purge_tenant_rows``. Edition Scope: Both (CE closeout core).
"""

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
    """The REST dashboard "Complete Project" action force-decommissions any
    still-active straggler agent (``close_project_and_update_memory(force=True)``).
    Before BE-9273 that decommission landed in the DB with zero WebSocket
    signal, so the dashboard agent tile stayed stale. This drives
    ``ProjectLifecycleService.complete_project`` (the exact REST
    /{project_id}/complete call shape: no db_session, so it owns and commits
    its own transaction) and proves the broadcast fires once that commit has
    genuinely landed.
    """
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
    finally:
        await purge_tenant_rows(db_manager, tenant_key)
        TenantManager.clear_current_tenant()


async def test_rest_selfheal_complete_project_no_agents_emits_nothing(db_manager) -> None:
    """No active agents to decommission -> no events, no broadcast call at all
    (must not emit a spurious empty event)."""
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
