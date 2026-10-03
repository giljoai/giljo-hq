# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.


from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, ProjectStatus
from giljo_mcp.services.project_staging_service import ProjectStagingService


pytestmark = pytest.mark.asyncio


def _staging_service(db_manager, tenant_key, db_session) -> ProjectStagingService:
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    return ProjectStagingService(db_manager=db_manager, tenant_manager=mock_tm, test_session=db_session)


async def _staged_project(db_session, tenant_key: str, *, active: bool) -> Project:
    product = Product(id=str(uuid4()), tenant_key=tenant_key, name=f"be9532-product-{uuid4().hex[:8]}")
    db_session.add(product)
    await db_session.flush()

    project = Project(
        id=str(uuid4()),
        tenant_key=tenant_key,
        product_id=product.id,
        name=f"be9532-project-{uuid4().hex[:8]}",
        description="BE-9532 launch-reporting probe.",
        mission="BE-9532 probe mission.",
        status=ProjectStatus.ACTIVE if active else ProjectStatus.INACTIVE,
        staging_status="staging_complete",
        implementation_launched_at=None if active else datetime.now(UTC),
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def test_launch_reports_that_activation_is_still_required(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _staged_project(db_session, test_tenant_key, active=False)

    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["success"] is True

    assert "project_active" in result, (
        "the launch result says nothing about activation -- a caller is told 'success' "
        "and cannot tell that the dashboard will show No Active Project"
    )
    assert result["project_active"] is False

    action = result.get("next_action")
    assert action, "an inactive project after launch must name the step still required"
    rendered = str(action).lower()
    assert "activ" in rendered, f"next_action must point at activation, got: {action!r}"


async def test_launch_on_an_active_project_asks_for_nothing_further(db_manager, db_session, test_tenant_key):
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _staged_project(db_session, test_tenant_key, active=True)

    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["success"] is True
    assert result["project_active"] is True
    assert not result.get("next_action"), (
        f"an already-active project needs no further step, got: {result.get('next_action')!r}"
    )


async def test_mcp_tool_passes_the_activation_report_through_to_the_agent(
    db_manager, db_session, test_tenant_key, monkeypatch
):
    from giljo_mcp.tools.tool_accessor._project_tools import ProjectToolsMixin

    project = await _staged_project(db_session, test_tenant_key, active=False)

    captured: dict = {}

    class _Recorder:
        def __init__(self, *a, **kw):
            pass

        async def launch_implementation(self, project_id, **kwargs):
            captured["origin"] = kwargs.get("origin")
            svc = _staging_service(db_manager, test_tenant_key, db_session)
            return await svc.launch_implementation(project_id, tenant_key=test_tenant_key)

    monkeypatch.setattr(
        "giljo_mcp.services.project_staging_service.ProjectStagingService",
        _Recorder,
    )

    accessor = ProjectToolsMixin()
    accessor.db_manager = db_manager
    accessor.tenant_manager = MagicMock()
    accessor.tenant_manager.get_current_tenant.return_value = test_tenant_key
    accessor.websocket_manager = None
    accessor._test_session = db_session
    accessor._websocket_manager = None

    payload = await accessor.launch_implementation(project_id=project.id, tenant_key=test_tenant_key)

    assert payload["status"] == "launched"
    assert payload.get("project_active") is False, (
        "the agent-facing payload lost the activation report -- this is exactly the "
        "shape of the original defect: a confident 'launched' with nothing said about "
        "the project still being invisible on the dashboard"
    )
    assert "activ" in str(payload.get("next_action", "")).lower()
    assert captured["origin"] == "mcp", "the headless door must still identify itself as mcp (TSK-6219)"
