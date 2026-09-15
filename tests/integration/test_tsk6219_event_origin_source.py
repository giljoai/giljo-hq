# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

import random
from uuid import uuid4

import pytest

from giljo_mcp.models.organizations import Organization
from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project
from giljo_mcp.services.project_staging_service import ProjectStagingService
from giljo_mcp.tools.tool_accessor import ToolAccessor


pytestmark = pytest.mark.asyncio

_EVENT = "project:implementation_launched"


class _CapturingWebSocketManager:

    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def broadcast_to_tenant(self, tenant_key: str, event_type: str, data: dict) -> None:
        self.calls.append({"tenant_key": tenant_key, "event_type": event_type, "data": data})

    def launch_payload(self) -> dict:
        for call in self.calls:
            if call["event_type"] == _EVENT:
                return call["data"]
        raise AssertionError(f"no {_EVENT} broadcast captured; saw {[c['event_type'] for c in self.calls]}")


async def _seed_staging_complete_project(db_session, tenant_key: str) -> str:
    suffix = uuid4().hex[:8]
    org = Organization(name=f"Org {suffix}", slug=f"org-{suffix}", tenant_key=tenant_key, is_active=True)
    db_session.add(org)
    await db_session.flush()

    product = Product(
        id=str(uuid4()),
        name=f"Product {suffix}",
        description="TSK-6219 event-origin tests",
        tenant_key=tenant_key,
        is_active=True,
        product_memory={},
    )
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"Project {suffix}",
        description="x",
        mission="x",
        status="active",
        execution_mode="claude_code_cli",
        staging_status="staging_complete",
        implementation_launched_at=None,
        series_number=random.randint(1, 9000),
    )
    db_session.add(project)
    await db_session.commit()
    return project.id


async def test_mcp_door_emits_source_mcp(db_manager, db_session):
    tenant_key = "tk_tsk6219_mcp"
    project_id = await _seed_staging_complete_project(db_session, tenant_key)
    ws = _CapturingWebSocketManager()

    accessor = ToolAccessor(
        db_manager=db_manager,
        tenant_manager=None,
        test_session=db_session,
        websocket_manager=ws,
    )
    result = await accessor.launch_implementation(project_id=project_id, tenant_key=tenant_key)
    assert result["already_launched"] is False

    assert ws.launch_payload().get("source") == "mcp"


async def test_ui_door_emits_source_ui(db_manager, db_session):
    tenant_key = "tk_tsk6219_ui"
    project_id = await _seed_staging_complete_project(db_session, tenant_key)
    ws = _CapturingWebSocketManager()

    service = ProjectStagingService(
        db_manager=db_manager,
        tenant_manager=None,
        test_session=db_session,
        websocket_manager=ws,
    )
    result = await service.launch_implementation(project_id=project_id, tenant_key=tenant_key, origin="ui")
    assert result["already_launched"] is False

    assert ws.launch_payload().get("source") == "ui"


async def test_no_origin_omits_source(db_manager, db_session):
    tenant_key = "tk_tsk6219_none"
    project_id = await _seed_staging_complete_project(db_session, tenant_key)
    ws = _CapturingWebSocketManager()

    service = ProjectStagingService(
        db_manager=db_manager,
        tenant_manager=None,
        test_session=db_session,
        websocket_manager=ws,
    )
    await service.launch_implementation(project_id=project_id, tenant_key=tenant_key)

    assert "source" not in ws.launch_payload()
