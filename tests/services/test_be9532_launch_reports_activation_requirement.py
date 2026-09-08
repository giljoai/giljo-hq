# Copyright (c) 2024-2026 GiljoAI LLC. All rights reserved.
# Licensed under the Elastic License 2.0.
# See LICENSE in the project root for terms.
# [CE] Community Edition.

"""BE-9532: a headless launch must SAY that activation is still required.

Found live during the S5b validation campaign, 2026-08-30, with the operator
watching his own dashboard. Driving a project entirely from the harness in the
documented order -- ``stage_project`` -> staging authored -> ``complete_job`` ->
``launch_implementation`` -> ``get_implementation_prompt`` -- produced
``{"success": true, "status": "launched"}`` while the project remained
``inactive`` and the Jobs pane rendered "No Active Project".

**What this is NOT.** The first diagnosis assumed launching should activate, and
a first attempt changed ``ProjectLaunchService`` -- a file the headless path
never executes (``launch_implementation`` routes through
``ProjectStagingService.launch_implementation``). Verifying the call path showed
something different and more interesting:

* Activation is a **deliberately separate step in BOTH doors.** The dashboard has
  its own Activate control (``POST /projects/{id}/activate``); the harness has
  ``update_project(status="active")``. Neither door activates as part of the
  launch, and the operator confirmed the dashboard has always worked that way.
* So there is no missing write, and making launch activate would be a real
  behaviour change to a deliberate design -- exactly what the museum rule exists
  to stop.

**The actual defect is that the harness never says so.** Nothing in
``launch_implementation``'s response, and nothing in the tool's ``next_action``,
mentions that the project is still inactive or that anything further is needed.
A user is told "launched, success", opens the dashboard, and finds an empty Jobs
pane with no error anywhere -- the human-as-courier failure ruling 19 exists to
remove, and a confident wrong impression of the same family as BE-9521.

The fix is therefore **structural reporting, not a new write**: the launch result
carries the project's activation state, and when the project is not active it
names the step that is still required. Both doors get it because it is added to
the single service both doors call.
"""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from sqlalchemy import select

from giljo_mcp.models.products import Product
from giljo_mcp.models.projects import Project, ProjectStatus
from giljo_mcp.services.project_staging_service import ProjectStagingService


pytestmark = pytest.mark.asyncio


def _staging_service(db_manager, tenant_key, db_session) -> ProjectStagingService:
    """Service bound to the TEST's session so rows written here are visible."""
    mock_tm = MagicMock()
    mock_tm.get_current_tenant.return_value = tenant_key
    return ProjectStagingService(db_manager=db_manager, tenant_manager=mock_tm, test_session=db_session)


async def _staged_project(db_session, tenant_key: str, *, active: bool) -> Project:
    """A project sitting exactly where a headless drive leaves it before launch."""
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
        created_at=datetime.now(UTC),
    )
    db_session.add(project)
    await db_session.flush()
    return project


async def test_launch_reports_that_activation_is_still_required(db_manager, db_session, test_tenant_key):
    """The live S5b failure, reproduced at the layer that owns the answer.

    Pre-fix the result is ``{success, implementation_launched_at, already_launched,
    launched_at}`` with no mention of activation at all -- which is precisely why
    the operator saw "launched: success" and an empty Jobs pane.
    """
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
    """The other half: no false alarm when the project is already active.

    Without this, a fix could satisfy the first test by always demanding
    activation -- advice that is wrong half the time is its own defect.
    """
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _staged_project(db_session, test_tenant_key, active=True)

    result = await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    assert result["success"] is True
    assert result["project_active"] is True
    assert not result.get("next_action"), (
        f"an already-active project needs no further step, got: {result.get('next_action')!r}"
    )


async def test_launch_still_does_not_activate(db_manager, db_session, test_tenant_key):
    """Pin the UNCHANGED half -- the museum rule's side of this project.

    Activation being separate is deliberate in both doors. If this ever fails,
    someone widened a reporting fix into a behaviour change; that is a distinct
    decision needing its own reproduction, not a side effect of this one.
    """
    svc = _staging_service(db_manager, test_tenant_key, db_session)
    project = await _staged_project(db_session, test_tenant_key, active=False)

    await svc.launch_implementation(project.id, tenant_key=test_tenant_key)

    row = (await db_session.execute(select(Project.status).where(Project.id == project.id))).scalar_one()
    assert row == ProjectStatus.INACTIVE, "launch must not silently activate -- that is a separate step by design"


async def test_mcp_tool_passes_the_activation_report_through_to_the_agent(
    db_manager, db_session, test_tenant_key, monkeypatch
):
    """The boundary test: the gap was that ONE DOOR said nothing, so pin that door.

    A service-level test alone would not have caught the reported defect -- what
    the operator hit was the MCP tool's payload, and the tool builds its own dict
    (``{"status": "launched", **result}``). If that spread is ever replaced by an
    explicit field list, the service can be perfectly correct while the agent-facing
    answer silently loses the very field this project added.
    """
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
